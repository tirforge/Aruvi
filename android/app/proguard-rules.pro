# Add project specific ProGuard rules here.

# Retrofit
-keep class kotlin.Metadata { *; }
-keep interface com.aruvi.tir.data.api.** { *; }
-dontwarn retrofit2.**
-keep class retrofit2.** { *; }
-keepattributes Signature
-keepattributes Exceptions
-keepattributes *Annotation*
-keepattributes EnclosingMethod

# Gson / Data Models
-keep class com.aruvi.tir.data.model.** { *; }
-keep class com.google.gson.** { *; }

# Hilt
-keep class dagger.hilt.** { *; }
-keep class javax.inject.** { *; }
-keep class * extends dagger.hilt.internal.define.ComponentProcessor

# ExoPlayer / Media3
-keep class androidx.media3.** { *; }

# Google Cast Framework
-keep class com.google.android.gms.cast.** { *; }
-keep class com.google.android.gms.cast.framework.** { *; }
-keep class androidx.mediarouter.app.MediaRouteActionProvider { *; }

# FFmpeg extension
-keep class com.github.ArmynC.** { *; }

# ZXing QR Code
-keep class com.google.zxing.** { *; }
-dontwarn com.google.zxing.**

# TV / Leanback (required for TV launcher to find the correct activity)
-keep class androidx.leanback.** { *; }
-keep class androidx.tv.** { *; }
-keep class com.aruvi.tir.ui.MainActivity { *; }
-keep class com.aruvi.tir.ui.mobile.MobileMainActivity { *; }
