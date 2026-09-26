package com.aruvi.tir.ui.mobile

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity

fun Context.findActivity(): ComponentActivity? {
    var ctx: Context? = this
    while (ctx != null) {
        when (ctx) {
            is ComponentActivity -> return ctx
            is ContextWrapper -> ctx = ctx.baseContext.takeIf { it !== ctx }
            else -> return null
        }
    }
    return null
}

fun Context.findFragmentActivity(): FragmentActivity? {
    var ctx: Context? = this
    while (ctx != null) {
        when (ctx) {
            is FragmentActivity -> return ctx
            is ContextWrapper -> ctx = ctx.baseContext.takeIf { it !== ctx }
            else -> return null
        }
    }
    return null
}
