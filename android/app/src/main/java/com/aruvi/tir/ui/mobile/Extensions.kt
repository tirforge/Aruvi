package com.aruvi.tir.ui.mobile

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity

fun Context.findActivity(): ComponentActivity? {
    // Iterative with a depth cap: a two-node wrapper cycle (A->B->A) would
    // recurse forever with a self-only guard and overflow the stack.
    var ctx: Context? = this
    var depth = 0
    while (ctx != null && depth < 20) {
        when (ctx) {
            is ComponentActivity -> return ctx
            is ContextWrapper -> {
                val base = ctx.baseContext
                if (base === ctx) return null
                ctx = base
            }
            else -> return null
        }
        depth++
    }
    return null
}

fun Context.findFragmentActivity(): FragmentActivity? {
    var ctx: Context? = this
    var depth = 0
    while (ctx != null && depth < 20) {
        when (ctx) {
            is FragmentActivity -> return ctx
            is ContextWrapper -> {
                val base = ctx.baseContext
                if (base === ctx) return null
                ctx = base
            }
            else -> return null
        }
        depth++
    }
    return null
}
