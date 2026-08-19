package com.aruvi.tir.ui.components

import android.content.Context
import android.media.AudioManager
import android.view.SoundEffectConstants

/**
 * TV navigation sounds using the system sound pool (zero assets).
 */
object TvSound {

    /** Played when a card gains focus. */
    fun navigate(context: Context) = play(context, SoundEffectConstants.NAVIGATION_RIGHT)

    /** Played when a card is pressed (DPad center). */
    fun click(context: Context) = play(context, SoundEffectConstants.CLICK)

    private fun play(context: Context, constant: Int) {
        runCatching {
            (context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager)
                ?.playSoundEffect(constant)
        }
    }
}
