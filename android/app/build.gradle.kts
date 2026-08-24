import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.dagger.hilt.android")
    kotlin("kapt")
}

android {
    namespace = "com.aruvi.tir"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    // Load local.properties at android block level
    val localProperties = Properties()
    val localPropertiesFile = rootProject.file("local.properties")
    if (localPropertiesFile.exists()) {
        localProperties.load(localPropertiesFile.inputStream())
    }

    flavorDimensions += "device"
    productFlavors {
        create("tv") {
            dimension = "device"
            targetSdk = 36
            versionCode = 16
            versionName = "2.0.1"
        }
        create("mobile") {
            dimension = "device"
            targetSdk = 36
            versionCode = 18
            versionName = "2.0.1"
        }
    }

    defaultConfig {
        applicationId = "com.aruvi.tir"
        minSdk = 28

        val serverUrl = localProperties.getProperty("TELEGRAM_TV_SERVER_URL", "http://localhost:7680")
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"$serverUrl\"")
    }

    signingConfigs {
        create("release") {
            // Prioritize environment variables for CI/CD, fallback to local.properties
            val storeFilePath = System.getenv("RELEASE_STORE_FILE") ?: localProperties.getProperty("RELEASE_STORE_FILE")
            val storeFileObj = if (storeFilePath != null) file(storeFilePath) else file("../my-release-key.jks")
            
            storeFile = storeFileObj
            storePassword = System.getenv("RELEASE_STORE_PASSWORD") ?: localProperties.getProperty("RELEASE_STORE_PASSWORD", "")
            keyAlias = System.getenv("RELEASE_KEY_ALIAS") ?: localProperties.getProperty("RELEASE_KEY_ALIAS", "my-key-alias")
            keyPassword = System.getenv("RELEASE_KEY_PASSWORD") ?: localProperties.getProperty("RELEASE_KEY_PASSWORD", "")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // Sign with the release key when provided (local/CI), otherwise fall
            // back to the auto-generated debug keystore so builds never need secrets.
            val releaseKeyConfigured = System.getenv("RELEASE_STORE_PASSWORD") != null
                || localProperties.getProperty("RELEASE_STORE_PASSWORD", "").isNotEmpty()
            signingConfig = if (releaseKeyConfigured) {
                signingConfigs.getByName("release")
            } else {
                // Debug-signed APKs can't be updated over a release-signed
                // install and are trivially re-signed by anyone — never ship
                // one without noticing.
                logger.warn(
                    "WARNING: release build is signed with the DEBUG keystore " +
                    "(no RELEASE_STORE_PASSWORD found). Do not distribute this APK."
                )
                signingConfigs.getByName("debug")
            }
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.8"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    // Single universal APK build (decoder AARs are small, so ABI splits are not needed)
    splits {
        abi {
            isEnable = false
            reset()
            include("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
            isUniversalApk = true
        }
    }
}

dependencies {
    // Kotlin
    implementation("org.jetbrains.kotlin:kotlin-stdlib:1.9.22")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // AndroidX Core
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.7.0")

    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.11.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.animation:animation")
    implementation("androidx.compose.animation:animation-core")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    // Compose for TV
    implementation("androidx.tv:tv-material:1.0.0")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.7.6")

    // Media3 (ExoPlayer) - Core
    implementation("androidx.media3:media3-exoplayer:1.2.1")
    implementation("androidx.media3:media3-ui:1.2.1")
    implementation("androidx.media3:media3-session:1.2.1")
    implementation("androidx.media3:media3-common:1.2.1")

    // Media3 - Format support
    implementation("androidx.media3:media3-exoplayer-dash:1.2.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.2.1")
    implementation("androidx.media3:media3-datasource-okhttp:1.2.1")

    // Chromecast - Media3 Cast extension
    implementation("androidx.media3:media3-cast:1.2.1")
    implementation("com.google.android.gms:play-services-cast-framework:21.5.0")

    // Software decoder extensions (AV1 video via local AAR, HEVC/H.264/VP8/VP9 + full audio via nextlib FFmpeg) - version-matched to media3 1.2.1
    implementation("com.github.anilbeesetti.nextlib:nextlib-media3ext:0.6.0")
    implementation(files("libs/lib-decoder-av1-release.aar"))
    implementation("androidx.mediarouter:mediarouter:1.6.0")
    implementation("androidx.appcompat:appcompat:1.6.1")

    // Note: Standard ExoPlayer supports HEVC, VP9, Opus, AAC, and most common formats
    // For DTS/AC3 software decoding, add FFmpeg extension manually if needed

    // Networking
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")

    // Dependency Injection - Hilt
    implementation("com.google.dagger:hilt-android:2.50")
    kapt("com.google.dagger:hilt-compiler:2.50")
    implementation("androidx.hilt:hilt-navigation-compose:1.1.0")

    // Image Loading - Coil
    implementation("io.coil-kt:coil-compose:2.5.0")

    // Security - Encrypted Preferences
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // Leanback (for TV-specific components not in Compose TV yet)
    implementation("androidx.leanback:leanback:1.0.0")

    // Datastore for preferences
    implementation("androidx.datastore:datastore-preferences:1.0.0")

    // QR Code generation for TV login
    implementation("com.google.zxing:core:3.5.3")

    // Testing
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}

kapt {
    correctErrorTypes = true
}
