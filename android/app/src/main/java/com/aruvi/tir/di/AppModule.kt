package com.aruvi.tir.di

import android.content.Context
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Hilt module for app-level dependencies.
 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    // Repositories are provided by @Inject constructors
}
