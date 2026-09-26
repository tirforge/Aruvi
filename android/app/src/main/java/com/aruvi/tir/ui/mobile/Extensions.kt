package com.aruvi.tir.ui.mobile

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity

fun Context.findActivity(): ComponentActivity? {
    var ctx: Context? = this
    var depth = 0
    while (ctx != null && depth < 32) {
        when (ctx) {
            is ComponentActivity -> return ctx
            is ContextWrapper -> ctx = ctx.baseContext
            else -> return null
        }
        depth++
    }
    return null
}

fun Context.findFragmentActivity(): FragmentActivity? {
    var ctx: Context? = this
    var depth = 0
    while (ctx != null && depth < 32) {
        when (ctx) {
            is FragmentActivity -> return ctx
            is ContextWrapper -> ctx = ctx.baseContext
            else -> return null
        }
        depth++
    }
    return null
}
