import AVFoundation
import Foundation
import UserNotifications

/// Always-on listening, plus whisper playback.
///
/// Once started it keeps listening until the owner pauses it, reconnecting by itself if the
/// server drops. Microphone audio goes up as mono PCM16 at 16 kHz, 100 ms at a time. A whisper
/// comes back as a short clip and plays on whatever output the phone is routed to. Holding the
/// talk button borrows the same microphone: those seconds go to the agent instead of into the
/// conversation.
///
/// Everything here runs on the main thread except the microphone tap, which only converts the
/// audio and hands it over.
final class ListenEngine: NSObject, URLSessionWebSocketDelegate, UNUserNotificationCenterDelegate {
    static let shared = ListenEngine()

    private enum Mode { case idle, listen, enroll }

    private static let rate: Double = 16000
    private static let chunkBytes = 3200 // 100 ms of mono PCM16 at 16 kHz
    private static let enrolSeconds: Double = 10

    private let hub = Hub.shared
    private var mode: Mode = .idle
    private var enrolName = "Me"

    // The live socket.
    private var urlSession: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var socketOpen = false
    private var pingTimer: Timer?
    private var scheduled: [DispatchWorkItem] = []

    // Audio.
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var playerAttached = false
    private var playerRate: Double = 0
    private var capturing = false
    private var wantCapture = false
    private var pending = Data()
    private var deadChunks = 0
    private var talk: Data?
    private var playToken = 0
    private var restartWork: DispatchWorkItem?
    private var observing = false

    private let wireFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: ListenEngine.rate, channels: 1, interleaved: true)

    private override init() {
        super.init()
    }

    // MARK: - What the screens call

    static var micAllowed: Bool {
        AVAudioSession.sharedInstance().recordPermission == .granted
    }

    /// The owner was asked and said no; iOS will not ask again.
    static var micDenied: Bool {
        AVAudioSession.sharedInstance().recordPermission == .denied
    }

    static func askForMic(_ done: @escaping (Bool) -> Void) {
        AVAudioSession.sharedInstance().requestRecordPermission { granted in
            DispatchQueue.main.async { done(granted) }
        }
    }

    /// Asks to show notifications, and lets them appear while the app is open.
    func prepareNotifications() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// Start, or resume, always-on listening.
    func start() {
        Prefs.set("paused", "no")
        begin(.listen)
    }

    /// Record the owner's voice for ten seconds, then carry on into listening.
    func enroll(name: String) {
        enrolName = name.isEmpty ? "Me" : name
        begin(.enroll)
    }

    /// Pause: tell the server, stop the microphone, and wait for the recap before closing.
    func pause() {
        Prefs.set("paused", "yes")
        finish()
    }

    /// A typed question asked into the live conversation.
    func ask(_ text: String) {
        send("ask", ["text": text])
    }

    // MARK: - Connection

    private func begin(_ newMode: Mode) {
        guard ListenEngine.micAllowed else {
            hub.error = "Wingman needs the microphone permission."
            return
        }
        if socket != nil && mode == newMode { return }
        closeSocket()
        cancelScheduled()
        mode = newMode
        connect()
    }

    private func connect() {
        if !hub.listening { hub.status = "Connecting" }
        hub.error = nil
        guard let url = Config.socketURL else {
            hub.error = "The server address \(Config.host) is not valid. Change it in Settings."
            hub.status = "Paused"
            mode = .idle
            return
        }
        if urlSession == nil {
            urlSession = URLSession(configuration: .default, delegate: self, delegateQueue: OperationQueue.main)
        }
        guard let session = urlSession else { return }
        var request = URLRequest(url: url)
        request.setValue(Config.key, forHTTPHeaderField: Config.keyHeader)
        let task = session.webSocketTask(with: request)
        // A spoken answer arrives as one message and can be well over the default 1 MB limit.
        task.maximumMessageSize = 32 * 1024 * 1024
        socket = task
        socketOpen = false
        task.resume()
        receive(on: task)
        // The microphone starts now rather than when the socket opens, so the app stays awake
        // in the background while it is still trying to reach the server.
        startCapture()
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self, self.socket === task else { return }
                switch result {
                case .failure:
                    self.dropped(task)
                case .success(let message):
                    switch message {
                    case .string(let text):
                        self.handle(text, from: task)
                    case .data(let data):
                        if let text = String(data: data, encoding: .utf8) { self.handle(text, from: task) }
                    @unknown default:
                        break
                    }
                    if self.socket === task { self.receive(on: task) }
                }
            }
        }
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol chosen: String?) {
        DispatchQueue.main.async {
            guard self.socket === webSocketTask else { return }
            self.socketOpen = true
            self.startPinging()
            if self.mode == .enroll {
                self.send("enroll_start", ["name": self.enrolName])
                self.later(ListenEngine.enrolSeconds) { self.send("enroll_stop") }
            } else {
                self.send("start")
            }
            self.startCapture()
        }
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        DispatchQueue.main.async { self.dropped(webSocketTask) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        DispatchQueue.main.async { self.dropped(task) }
    }

    private func handle(_ text: String, from task: URLSessionWebSocketTask) {
        guard let event = JSON.parse(text), event.isObject else { return }
        switch event["type"].string {
        case "audio":
            // A check-in is never said out of the phone's speaker: earbuds, or a notification.
            if event["kind"].string == "checkin" && noEarbuds() {
                notify("Wingman", event["text"].string)
            } else if !silentWithoutEarbuds() {
                let rate = event["sampleRate"].isNull ? ListenEngine.rate : event["sampleRate"].double
                play(event["pcm"].string, rate: rate)
            }
        case "whisper":
            hub.handle(event)
            if event["outcome"].string == "spoken" && event["kind"].string != "checkin" && silentWithoutEarbuds() {
                notify("Wingman", event["text"].string)
            }
        case "stop_audio":
            stopPlaying()
        case "reminder":
            hub.handle(event)
            notify("Reminder", event["text"].string)
        case "research":
            hub.handle(event)
            notify("Research ready", event["topic"].string)
        case "enrolled":
            hub.handle(event)
            // After the voice sample, carry straight on into always-on listening.
            closeSocket()
            if event["ok"].bool && Prefs.get("paused") != "yes" {
                begin(.listen)
            } else {
                shutdown()
            }
        case "ended":
            hub.handle(event)
            shutdown()
        case "superseded":
            // Another of the owner's devices took over listening; step aside quietly.
            shutdown()
            hub.handle(event)
        default:
            hub.handle(event)
        }
    }

    /// The connection went away. Always-on means trying again, unless the owner paused.
    private func dropped(_ which: URLSessionTask) {
        guard let current = socket, current === which else { return }
        socket = nil
        socketOpen = false
        stopPinging()
        hub.listening = false
        hub.hearing = false
        hub.enrolling = false
        if mode == .listen && Prefs.get("paused") != "yes" {
            hub.status = "Reconnecting"
            hub.error = Config.keyIsPlaceholder
                ? "Cannot reach the Wingman server at \(Config.host). The app key has not been set: add it in Settings. Retrying."
                : "Cannot reach the Wingman server at \(Config.host). Retrying."
            later(3) {
                if self.socket == nil && self.mode == .listen { self.connect() }
            }
        } else {
            if mode == .enroll {
                hub.error = Config.keyIsPlaceholder
                    ? "Cannot reach the Wingman server at \(Config.host). The app key has not been set."
                    : "Cannot reach the Wingman server at \(Config.host)."
            }
            hub.status = "Paused"
            shutdown()
        }
    }

    private func finish() {
        if socket == nil {
            shutdown()
            return
        }
        stopCapture()
        stopPlaying()
        hub.status = "Writing recap"
        send("stop")
        later(20) { self.shutdown() }
    }

    private func shutdown() {
        mode = .idle
        cancelScheduled()
        if talk == nil { stopCapture() }
        stopPlaying()
        closeSocket()
        hub.listening = false
        hub.hearing = false
        hub.enrolling = false
        if !hub.status.hasPrefix("Listening on") { hub.status = "Paused" }
    }

    private func closeSocket() {
        stopPinging()
        if let task = socket {
            socket = nil
            socketOpen = false
            task.cancel(with: .normalClosure, reason: nil)
        }
    }

    private func send(_ type: String, _ fields: [String: String] = [:]) {
        guard let task = socket, socketOpen else { return }
        var message: [String: Any] = ["type": type]
        for (key, value) in fields { message[key] = value }
        guard let data = try? JSONSerialization.data(withJSONObject: message, options: []),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    private func startPinging() {
        stopPinging()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            guard let self = self, let task = self.socket, self.socketOpen else { return }
            task.sendPing { _ in }
        }
    }

    private func stopPinging() {
        pingTimer?.invalidate()
        pingTimer = nil
    }

    private func later(_ seconds: Double, _ block: @escaping () -> Void) {
        let work = DispatchWorkItem(block: block)
        scheduled.append(work)
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }

    private func cancelScheduled() {
        scheduled.forEach { $0.cancel() }
        scheduled.removeAll()
    }

    // MARK: - Microphone

    private func activateSession() throws {
        let session = AVAudioSession.sharedInstance()
        // Record and play at once; Bluetooth earbuds for both; other audio is lowered. Without
        // earbuds the sound comes from the loudspeaker, as on Android, not the earpiece.
        try session.setCategory(.playAndRecord, mode: .default,
                                options: [.allowBluetooth, .allowBluetoothA2DP, .duckOthers, .defaultToSpeaker])
        try session.setActive(true, options: [])
        if !observing {
            observing = true
            let center = NotificationCenter.default
            center.addObserver(self, selector: #selector(audioChanged(_:)), name: .AVAudioEngineConfigurationChange, object: engine)
            center.addObserver(self, selector: #selector(audioInterrupted(_:)), name: AVAudioSession.interruptionNotification, object: nil)
            center.addObserver(self, selector: #selector(audioChanged(_:)), name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
        }
    }

    /// The player is wired to the mixer in the clip's own format; the mixer does the resampling.
    private func wirePlayer(rate: Double) {
        if !playerAttached {
            engine.attach(player)
            playerAttached = true
        }
        if playerRate != rate, let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1) {
            player.stop()
            engine.connect(player, to: engine.mainMixerNode, format: format)
            playerRate = rate
        }
    }

    private func startCapture() {
        wantCapture = true
        if capturing { return }
        guard let wire = wireFormat else { return }
        do {
            try activateSession()
        } catch {
            hub.error = "Could not open the microphone."
            retryCapture()
            return
        }
        wirePlayer(rate: playerRate > 0 ? playerRate : ListenEngine.rate)
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0,
              let converter = AVAudioConverter(from: format, to: wire) else {
            hub.error = "Could not open the microphone."
            retryCapture()
            return
        }
        let ratio = wire.sampleRate / format.sampleRate
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            // On the audio thread: convert to 16 kHz mono PCM16, then hand over to the main thread.
            guard buffer.frameLength > 0 else { return }
            let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
            guard let out = AVAudioPCMBuffer(pcmFormat: wire, frameCapacity: capacity) else { return }
            var fed = false
            var problem: NSError?
            let status = converter.convert(to: out, error: &problem) { _, outStatus in
                if fed {
                    outStatus.pointee = .noDataNow
                    return nil
                }
                fed = true
                outStatus.pointee = .haveData
                return buffer
            }
            guard status != .error, out.frameLength > 0, let samples = out.int16ChannelData else { return }
            let data = Data(bytes: samples[0], count: Int(out.frameLength) * 2)
            DispatchQueue.main.async { self?.heard(data) }
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            hub.error = "Could not open the microphone."
            retryCapture()
            return
        }
        pending.removeAll()
        deadChunks = 0
        capturing = true
    }

    private func stopCapture() {
        wantCapture = false
        restartWork?.cancel()
        restartWork = nil
        guard capturing else { return }
        capturing = false
        engine.inputNode.removeTap(onBus: 0)
        pending.removeAll()
        LevelMeter.shared.level = 0
        // The engine keeps running while a clip is still playing; `stopPlaying` ends it.
        if !player.isPlaying { stopEngine() }
    }

    private func stopEngine() {
        if engine.isRunning { engine.stop() }
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    /// Reopen the microphone: the route changed, a call ended, or the stream went dead.
    private func restartCapture() {
        guard wantCapture else { return }
        if capturing {
            capturing = false
            engine.inputNode.removeTap(onBus: 0)
        }
        if engine.isRunning { engine.stop() }
        startCapture()
    }

    private func retryCapture(after seconds: Double = 2) {
        restartWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.restartCapture() }
        restartWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }

    @objc private func audioChanged(_ notification: Notification) {
        DispatchQueue.main.async {
            guard self.wantCapture else { return }
            self.retryCapture(after: 0.5)
        }
    }

    @objc private func audioInterrupted(_ notification: Notification) {
        let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt ?? 0
        DispatchQueue.main.async {
            guard self.wantCapture else { return }
            if raw == AVAudioSession.InterruptionType.began.rawValue {
                self.hub.whispering = false
                LevelMeter.shared.level = 0
            } else {
                self.retryCapture(after: 0.5)
            }
        }
    }

    /// Converted microphone audio, on the main thread. Cut into 100 ms pieces and sent.
    private func heard(_ data: Data) {
        guard capturing else { return }
        pending.append(data)
        while pending.count >= ListenEngine.chunkBytes {
            let chunk = Data(pending.prefix(ListenEngine.chunkBytes))
            pending = Data(pending.dropFirst(ListenEngine.chunkBytes))
            process(chunk)
        }
    }

    private func process(_ chunk: Data) {
        // Loudness of this tenth of a second, for the waveform on screen.
        var peak = 0
        chunk.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            let samples = raw.bindMemory(to: Int16.self)
            for sample in samples {
                let size = abs(Int(Int16(littleEndian: sample)))
                if size > peak { peak = size }
            }
        }
        LevelMeter.shared.level = min(1, CGFloat(peak) / 9000)
        // Eight seconds of exact zeros means the stream has died, not that the room is quiet:
        // reopen the microphone rather than listen to nothing.
        deadChunks = peak == 0 ? deadChunks + 1 : 0
        if deadChunks >= 80 {
            deadChunks = 0
            retryCapture(after: 0.1)
            return
        }
        if talk != nil {
            talk?.append(chunk)
        } else if let task = socket, socketOpen {
            task.send(.data(chunk)) { _ in }
        }
    }

    // MARK: - Talking to the agent

    func talkStart() {
        guard ListenEngine.micAllowed else {
            hub.error = "Wingman needs the microphone permission."
            return
        }
        stopPlaying()
        talk = Data()
        if !capturing { startCapture() }
        hub.talking = true
    }

    func talkStop() {
        guard let clip = talk else { return }
        talk = nil
        if mode == .idle { stopCapture() }
        hub.talking = false
        hub.thinking = true
        Task { @MainActor in
            let answer = await Server.voice(clip)
            self.hub.thinking = false
            guard let answer = answer, answer.isObject else {
                self.hub.chat.append(ChatMessage(role: "wingman", text: "I could not hear that, or the server did not answer."))
                return
            }
            let heard = answer["heard"].string
            if !heard.isEmpty { self.hub.chat.append(ChatMessage(role: "you", text: heard)) }
            self.hub.chat.append(ChatMessage.from(answer))
            let audio = answer["audio"].string
            if !audio.isEmpty {
                let rate = answer["sampleRate"].isNull ? ListenEngine.rate : answer["sampleRate"].double
                self.play(audio, rate: rate)
            }
        }
    }

    // MARK: - Whispers and spoken answers

    private func play(_ encoded: String, rate: Double) {
        guard let pcm = Data(base64Encoded: encoded, options: [.ignoreUnknownCharacters]), pcm.count >= 2, rate > 0 else { return }
        do {
            try activateSession()
        } catch {
            return
        }
        wirePlayer(rate: rate)
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1) else { return }
        let frames = pcm.count / 2
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)),
              let channels = buffer.floatChannelData else { return }
        buffer.frameLength = AVAudioFrameCount(frames)
        let out = channels[0]
        pcm.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            let samples = raw.bindMemory(to: Int16.self)
            for index in 0..<frames {
                out[index] = Float(Int16(littleEndian: samples[index])) / 32768
            }
        }
        if !engine.isRunning {
            engine.prepare()
            do {
                try engine.start()
            } catch {
                return
            }
        }
        player.stop()
        playToken += 1
        let token = playToken
        player.scheduleBuffer(buffer, at: nil, options: [], completionHandler: nil)
        player.play()
        hub.whispering = true
        let seconds = Double(frames) / rate + 0.15
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
            guard let self = self, self.playToken == token else { return }
            self.stopPlaying()
        }
    }

    private func stopPlaying() {
        playToken += 1
        if playerAttached && engine.isRunning { player.stop() }
        hub.whispering = false
        // Nothing left for the engine to do once the microphone is closed too.
        if !capturing && !wantCapture { stopEngine() }
    }

    // MARK: - Earbuds and notifications

    /// With "Only speak in earbuds" on and nothing in the ears, a whisper is shown instead of said.
    private func silentWithoutEarbuds() -> Bool {
        Prefs.get("earbudsOnly") == "1" && noEarbuds()
    }

    private func noEarbuds() -> Bool {
        let personal: [AVAudioSession.Port] = [.headphones, .bluetoothA2DP, .bluetoothHFP, .bluetoothLE, .usbAudio]
        let outputs = AVAudioSession.sharedInstance().currentRoute.outputs
        return !outputs.contains { personal.contains($0.portType) }
    }

    /// A reminder is spoken, and also shown, in case the earbuds are out.
    private func notify(_ title: String, _ text: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = text.capitalisedFirst
        content.sound = UNNotificationSound.default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
