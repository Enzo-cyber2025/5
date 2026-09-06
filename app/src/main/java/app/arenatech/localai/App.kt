package app.arenatech.localai

import android.app.Application
import android.content.Context
import app.arenatech.localai.data.ChatStore
import app.arenatech.localai.data.ModelStore
import app.arenatech.localai.data.Prefs

class App : Application() {

    override fun onCreate() {
        super.onCreate()
        appContext = applicationContext
        Prefs.init(this)
        ChatStore.init(this)
        ModelStore.init(this)
    }

    companion object {
        lateinit var appContext: Context
            private set
    }
}
