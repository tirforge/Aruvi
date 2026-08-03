# Web Player No Audio Analysis

**Date:** 2026-07-24  
**Issue:** Playing ~3GB movie on web — video shows fine but no audio  
**Environment:** Web (native `<video>` element via TelePlay frontend React app)  
**App Version:** Apps work fine (ExoPlayer on Android supports these codecs)

---

## Summary

The root cause is an **unsupported audio codec** in the 3GB movie file. High-quality movie rips typically use audio codecs (AC-3/Dolby Digital, E-AC-3, DTS, DTS-HD, TrueHD) that **web browsers cannot decode natively**. The browser plays the video track (H.264/H.265 — well supported) but silently drops the audio track with **no error event**.

---

## Key Findings

### 1. Browser Audio Codec Limitations
Browsers only support these audio codecs in the native `<video>` element:
| Browser | Supported Audio Codecs |
|---------|----------------------|
| Chrome | AAC, MP3, Opus, Vorbis, FLAC |
| Firefox | AAC, MP3, Opus, Vorbis, FLAC |
| Safari | AAC, MP3, Opus, Vorbis, FLAC, AC-3 (partial) |

**NOT supported by any browser:** DTS, DTS-HD, TrueHD, Atmos (raw), E-AC-3 (except Safari partial)

### 2. 3GB Movie Audio Profile
A ~3GB movie file typically contains:
- **Video:** H.264/AVC or H.265/HEVC ✅ (browser supported)
- **Audio:** AC-3, E-AC-3, DTS, or TrueHD ❌ (browser NOT supported)

### 3. Critical Bug: No Error Fires
The player has an error handler:

```jsx
const handleError = () => {
    if (videoRef.current?.error) {
        const code = videoRef.current.error.code;
        if (code === 3 || code === 4) {
            setError("Browser cannot decode this video format.");
        }
    }
};
```

But **browsers do NOT fire `error` events when the video codec works but the audio codec doesn't**. The `<video>` element considers the stream "playable" as long as it can decode the container and any one track. The audio track is silently ignored.

This means the user sees a playing video with no error, no audio, and no indication of why.

### 4. Audio Track Detection Fails on Most Browsers
The player tries to detect audio tracks via:

```jsx
const tracks = (video as any).audioTracks;
```

The `HTMLVideoElement.audioTracks` property:
- ❌ **Chrome**: Returns empty `AudioTrackList` (always 0 tracks)
- ❌ **Firefox**: Not supported at all (`undefined`)
- ✅ **Safari**: Works (returns actual tracks)

So the "Audio Track" switcher in settings almost never appears on Chrome/Firefox.

### 5. Why Android App Works Fine
The Android app uses **ExoPlayer (Media3)** with:
```kotlin
DefaultRenderersFactory(context)
    .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
```

This enables FFmpeg extension decoders for AC-3, E-AC-3, DTS, etc. — codecs the Android build includes via the `media3-exoplayer-ffmpeg-extension`.

### 6. Backend Streaming is Correct
The streaming backend (`routers/streaming.py`) sends the correct `Content-Type` from the database and supports byte-range seeking. Nothing wrong here.

---

## What Happens Step-by-Step

1. User opens web player for the 3GB movie
2. Browser fetches stream URL with byte-range support
3. Backend streams raw file bytes from Telegram via MTProto
4. Browser parses the container (e.g., MKV)
5. ✅ **Video track** (H.264) starts decoding — picture shows
6. ❌ **Audio track** (e.g., AC-3 or DTS) — browser can't decode
7. Browser **silently ignores** the audio track — no error
8. User sees video playing with zero audio
9. Volume controls work but there's nothing to amplify

---

## Solutions

### Immediate (user can do now)
- **Use the Android app** — ExoPlayer supports these codecs
- **Click "Open in VLC"** button in the web player (already built in)
- **Download the file** and play locally (VLC, MPV, etc.)
- **Use Copy URL** to paste into an external player

### Code Fix (to improve UX)
The player should **detect the silent audio failure** and show a warning. Options:

**Option A — Error banner for unsupported audio:**
After `loadedmetadata`, wait 2-3 seconds, then check if `audioTracks` is empty or `audioTracks.length === 0` for video files. Show a non-blocking banner: "This video has no audio or uses an unsupported audio codec. Try opening in VLC."

**Option B — Detect via audio context:**
Create a silent `AudioContext`, connect the video element, and monitor if any audio data flows. If none after 5 seconds, show warning. (Complex, fragile.)

**Option C — File-level detection:**
The backend already stores `mime_type`. If the file is `video/x-matroska` and over 1GB, it's highly likely to have DTS/AC-3 audio. The frontend could check file metadata and show a pre-emptive "This file may contain audio not supported by your browser" message with the VLC button.

---

## Sources

1. [MediaPlayer.tsx](https://github.com/Thirupathi-pirate/teleplay-frontend/blob/main/src/components/MediaPlayer.tsx) — Web player source code
2. [routers/streaming.py](file:///home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/routers/streaming.py) — Backend streaming endpoint
3. [PlayerModule.kt](file:///home/thirupathi/Desktop/Aruvi/app/src/main/java/com/aruvi/tir/di/PlayerModule.kt) — Android ExoPlayer config with extension renderers
4. [HTMLMediaElement.audioTracks MDN](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/audioTracks) — Browser support for audioTracks API
5. [Can I Use: AAC / AC-3](https://caniuse.com/?search=ac-3) — Browser audio codec support matrix
