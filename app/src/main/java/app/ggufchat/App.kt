package app.ggufchat

import android.app.Application
import app.ggufchat.core.CoreEngine
import app.ggufchat.data.Repo
import app.ggufchat.data.Store
import app.ggufchat.service.GenService
import kotlinx.coroutines.launch

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Store.init(this)
        Repo.boot()
        GenService.ensureChannel(this)
        // o init nativo é barato; garante a detecção de Vulkan cedo
        CoreEngine.scope.launch {
            runCatching { CoreEngine.ensureInit() }
        }
    }
}
