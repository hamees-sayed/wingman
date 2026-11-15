import CoreText
import SwiftUI
import UIKit

// Wingman's look: paper and ink, one blue, an editorial serif for anything Wingman "says",
// a plain sans for controls, and a monospace for times and labels.

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: alpha)
    }
}

enum Palette {
    static let paper = Color(hex: 0xF7F8FB)
    static let ink = Color(hex: 0x0B1026)
    static let muted = Color(hex: 0x646C87)
    static let hair = Color(hex: 0xE3E6EF)
    static let accent = Color(hex: 0x2B50FF)
    static let accentSoft = Color(hex: 0xE8EDFF)
    static let night = Color(hex: 0x070B1C)
    static let nightText = Color(hex: 0xAEB6D6)
    static let nightAccent = Color(hex: 0x9DB1FF)
    static let nightError = Color(hex: 0xFFB4A8)
    static let due = Color(hex: 0xB86E00)
    static let dueSoft = Color(hex: 0xFFF1D9)
    static let good = Color(hex: 0x14804A)
    static let goodSoft = Color(hex: 0xDDF5E8)
    static let bad = Color(hex: 0xB3261E)
    static let badSoft = Color(hex: 0xFDE7E4)
}

/// The three families. Each falls back to a system font if the bundled file did not load.
enum Typeface {
    private static let serifName = "InstrumentSerif-Regular"
    private static let serifItalicName = "InstrumentSerif-Italic"
    private static let sansName = "Geist-Regular"
    private static let monoName = "GeistMono-Regular"

    private static let hasSerif = UIFont(name: serifName, size: 12) != nil
    private static let hasSerifItalic = UIFont(name: serifItalicName, size: 12) != nil
    private static let hasSans = UIFont(name: sansName, size: 12) != nil
    private static let hasMono = UIFont(name: monoName, size: 12) != nil

    /// Geist and Geist Mono are variable fonts: the weight is set on the 'wght' axis.
    private static func variable(_ name: String, size: CGFloat, weight: CGFloat) -> Font {
        let axis = NSNumber(value: 2003265652) // 'wght'
        let variation = UIFontDescriptor.AttributeName(rawValue: kCTFontVariationAttribute as String)
        let descriptor = UIFontDescriptor(fontAttributes: [
            UIFontDescriptor.AttributeName.name: name,
            variation: [axis: NSNumber(value: Double(weight))],
        ])
        let font = UIFont(descriptor: descriptor, size: size)
        return Font(font as CTFont)
    }

    static func serif(_ size: CGFloat, italic: Bool = false) -> Font {
        if italic {
            return hasSerifItalic ? Font.custom(serifItalicName, fixedSize: size) : Font.system(size: size, design: .serif).italic()
        }
        return hasSerif ? Font.custom(serifName, fixedSize: size) : Font.system(size: size, design: .serif)
    }

    static func sans(_ size: CGFloat, weight: CGFloat = 400) -> Font {
        if hasSans { return variable(sansName, size: size, weight: weight) }
        let system: Font.Weight = weight >= 700 ? .bold : weight >= 600 ? .semibold : weight >= 500 ? .medium : .regular
        return Font.system(size: size, weight: system)
    }

    static func mono(_ size: CGFloat, weight: CGFloat = 500) -> Font {
        if hasMono { return variable(monoName, size: size, weight: weight) }
        return Font.system(size: size, weight: .medium, design: .monospaced)
    }
}

/// The dark surface used for the hero card and onboarding: ink with a blue glow in one corner.
struct NightBackground: View {
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            ZStack {
                Palette.night
                RadialGradient(
                    gradient: Gradient(colors: [Color(hex: 0x3558FF), Color(hex: 0x3558FF, alpha: 0.4), Color(hex: 0x070B1C, alpha: 0)]),
                    center: UnitPoint(x: 0.92, y: 0.02), startRadius: 0, endRadius: max(1, width * 0.95))
                RadialGradient(
                    gradient: Gradient(colors: [Color(hex: 0x22C7E8, alpha: 0.33), Color(hex: 0x070B1C, alpha: 0)]),
                    center: UnitPoint(x: 0.05, y: 1.02), startRadius: 0, endRadius: max(1, width * 0.7))
            }
        }
    }
}

/// Serif text: headlines, and anything in Wingman's own voice.
struct DisplayText: View {
    let text: String
    let size: CGFloat
    var color: Color = Palette.ink
    var italic: Bool = false
    var lines: Int? = nil

    init(_ text: String, _ size: CGFloat, _ color: Color = Palette.ink, italic: Bool = false, lines: Int? = nil) {
        self.text = text
        self.size = size
        self.color = color
        self.italic = italic
        self.lines = lines
    }

    var body: some View {
        Text(text)
            .font(Typeface.serif(size, italic: italic))
            .tracking(-0.3)
            .foregroundColor(color)
            .lineLimit(lines)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Sans text for everything functional.
struct BodyText: View {
    let text: String
    let size: CGFloat
    var color: Color = Palette.ink
    var weight: CGFloat = 400
    var lines: Int? = nil

    init(_ text: String, _ size: CGFloat = 15, _ color: Color = Palette.ink, weight: CGFloat = 400, lines: Int? = nil) {
        self.text = text
        self.size = size
        self.color = color
        self.weight = weight
        self.lines = lines
    }

    var body: some View {
        Text(text)
            .font(Typeface.sans(size, weight: weight))
            .lineSpacing(size * 0.2)
            .foregroundColor(color)
            .lineLimit(lines)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Small capitals in monospace: section labels, times, states. Takes only the width it needs.
struct LabelText: View {
    let text: String
    var color: Color = Palette.muted

    init(_ text: String, _ color: Color = Palette.muted) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text.uppercased())
            .font(Typeface.mono(11))
            .tracking(1.3)
            .foregroundColor(color)
            .lineLimit(1)
    }
}

struct HairRule: View {
    var color: Color = Palette.hair

    var body: some View {
        Rectangle().fill(color).frame(height: 1).frame(maxWidth: .infinity)
    }
}

/// Wingman's signature: a row of bars that breathes on its own and swells with the microphone.
/// `level` is 0 to 1; `active` false flattens it to a resting line.
struct Wave: View {
    var level: CGFloat
    var active: Bool
    var color: Color
    var bars: Int = 40

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { context, size in
                let time = timeline.date.timeIntervalSinceReferenceDate
                let phase = time * 2 * Double.pi / 2.6
                let swell: Double = active ? 0.22 + Double(min(max(level, 0), 1)) * 0.78 : 0.06
                let count = max(bars, 2)
                let slot = size.width / CGFloat(count)
                let thick = slot * 0.46
                for index in 0..<count {
                    let across = Double(index) / Double(count - 1)
                    let envelope = sin(across * Double.pi) // tall in the middle, low at the ends
                    let ripple = abs(sin(phase + Double(index) * 0.52)) * 0.65 + abs(sin(phase * 1.7 + Double(index) * 0.21)) * 0.35
                    let share = min(1, 0.06 + swell * envelope * ripple)
                    let tall = size.height * CGFloat(share)
                    let rect = CGRect(x: CGFloat(index) * slot + (slot - thick) / 2, y: (size.height - tall) / 2, width: thick, height: tall)
                    context.fill(Path(roundedRect: rect, cornerRadius: thick / 2), with: .color(color.opacity(0.35 + 0.65 * envelope)))
                }
            }
        }
    }
}

/// A wave that follows the microphone.
struct LiveWave: View {
    @ObservedObject private var meter = LevelMeter.shared
    var active: Bool
    var color: Color

    var body: some View {
        Wave(level: meter.level, active: active, color: color)
    }
}

/// A pill button. `solid` fills it with ink (or white on a dark surface).
struct ActionButton: View {
    let text: String
    var solid: Bool = false
    var onDark: Bool = false
    var enabled: Bool = true
    var wide: Bool = false
    let action: () -> Void

    init(_ text: String, solid: Bool = false, onDark: Bool = false, enabled: Bool = true, wide: Bool = false, action: @escaping () -> Void) {
        self.text = text
        self.solid = solid
        self.onDark = onDark
        self.enabled = enabled
        self.wide = wide
        self.action = action
    }

    private var fill: Color {
        if !solid { return Color.clear }
        return onDark ? Color.white : Palette.ink
    }

    private var ink: Color {
        if solid && onDark { return Palette.night }
        if solid { return Color.white }
        return onDark ? Color.white : Palette.ink
    }

    var body: some View {
        Button(action: action) {
            Text(text)
                .font(Typeface.sans(14, weight: 600))
                .foregroundColor(enabled ? ink : ink.opacity(0.4))
                .lineLimit(1)
                .padding(.horizontal, 18)
                .frame(maxWidth: wide ? .infinity : nil)
                .frame(height: 46)
                .background(Capsule().fill(fill))
                .overlay(Capsule().stroke(solid ? Color.clear : (onDark ? Color.white.opacity(0.25) : Palette.hair), lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// A screen's title, with a small label above it and an optional back button.
struct Header<Trailing: View>: View {
    let title: String
    let kicker: String
    var back: (() -> Void)?
    let trailing: Trailing

    init(_ title: String, _ kicker: String, back: (() -> Void)? = nil, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.kicker = kicker
        self.back = back
        self.trailing = trailing()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            if let back = back {
                Button(action: back) {
                    Image(systemName: "arrow.left")
                        .font(.system(size: 17, weight: .medium))
                        .foregroundColor(Palette.ink)
                        .frame(width: 44, height: 44)
                        .overlay(Circle().stroke(Palette.hair, lineWidth: 1))
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Back")
                .padding(.top, 4)
                .padding(.trailing, 14)
            }
            VStack(alignment: .leading, spacing: 4) {
                LabelText(kicker)
                DisplayText(title, back != nil ? 30 : 40)
            }
            trailing
        }
        .padding(.horizontal, 24)
        .padding(.top, 18)
    }
}

extension Header where Trailing == EmptyView {
    init(_ title: String, _ kicker: String, back: (() -> Void)? = nil) {
        self.init(title, kicker, back: back) { EmptyView() }
    }
}

/// A section heading: a label, an optional count, an optional action on the right, and a rule.
struct SectionHeader: View {
    let label: String
    var count: Int?
    var action: String?
    var onAction: () -> Void

    init(_ label: String, count: Int? = nil, action: String? = nil, onAction: @escaping () -> Void = {}) {
        self.label = label
        self.count = count
        self.action = action
        self.onAction = onAction
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                LabelText(label, Palette.ink)
                if let count = count { LabelText("  \(count)", Palette.muted) }
                Spacer(minLength: 8)
                if let action = action {
                    Button(action: onAction) {
                        LabelText(action, Palette.accent)
                            .padding(.vertical, 10)
                            .padding(.horizontal, 4)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(minHeight: 34)
            .padding(.top, 30)
            .padding(.bottom, 10)
            HairRule(color: Palette.ink)
        }
    }
}

/// A small text button in label type.
struct LabelButton: View {
    let text: String
    var color: Color = Palette.accent
    var enabled: Bool = true
    let action: () -> Void

    init(_ text: String, _ color: Color = Palette.accent, enabled: Bool = true, action: @escaping () -> Void) {
        self.text = text
        self.color = color
        self.enabled = enabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            LabelText(text, color)
                .padding(10)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// A titled switch with a line of explanation.
struct ToggleRow: View {
    let title: String
    let detail: String
    let isOn: Bool
    let onChange: (Bool) -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                BodyText(title, 16, weight: 600)
                BodyText(detail, 13, Palette.muted)
            }
            Toggle("", isOn: Binding(get: { isOn }, set: { onChange($0) }))
                .labelsHidden()
                .tint(Palette.ink)
        }
        .padding(.vertical, 14)
    }
}

/// A coloured band of text across the top of a screen: an error, or something to act on.
struct Banner: View {
    let text: String
    let color: Color
    let soft: Color

    var body: some View {
        BodyText(text, 13, color)
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 14).fill(soft))
            .padding(.horizontal, 24)
            .padding(.top, 14)
    }
}
