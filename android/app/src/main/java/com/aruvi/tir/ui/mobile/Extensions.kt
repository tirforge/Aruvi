package com.aruvi.tir.ui.mobile

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity

fun Context.findActivity(): ComponentActivity? = when (this) {
    is ComponentActivity -> this
    is ContextWrapper -> if (baseContext === this) null else baseContext.findActivity()
    else -> null
}

fun Context.findFragmentActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> if (baseContext === this) null else baseContext.findFragmentActivity()
    else -> null
}
