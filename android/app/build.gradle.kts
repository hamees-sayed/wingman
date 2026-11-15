import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The app key, the server's address and the Google client id are not in the source. They come
// from android/local.properties (never committed) or, in CI, from environment variables.
val local = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun setting(name: String, env: String): String = (local.getProperty(name) ?: System.getenv(env) ?: "").trim()

android {
    namespace = "ai.wingman.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.wingman.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
        buildConfigField("String", "WINGMAN_KEY", "\"${setting("wingman.key", "WINGMAN_KEY")}\"")
        buildConfigField("String", "WINGMAN_SERVER", "\"${setting("wingman.server", "WINGMAN_SERVER")}\"")
        buildConfigField("String", "GOOGLE_WEB_CLIENT", "\"${setting("wingman.googleClient", "GOOGLE_WEB_CLIENT")}\"")
    }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.android.gms:play-services-auth:21.2.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
