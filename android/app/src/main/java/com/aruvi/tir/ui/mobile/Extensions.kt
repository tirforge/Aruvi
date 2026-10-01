package com.aruvi.tir.ui.mobile

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity

fun Context.findActivity(): ComponentActivity? {
    var ctx: Context? = this
    while (ctx != null) {
        if (ctx is ComponentActivity) return ctx
        ctx = if (ctx is ContextWrapper) ctx.baseContext else null
    }
    return null
}

fun Context.findFragmentActivity(): FragmentActivity? {
    var ctx: Context? = this
    while (ctx != null) {
        if (ctx is FragmentActivity) return ctx
        ctx = if (ctx is ContextWrapper) ctx.baseContext else null
    }
    return null
}
