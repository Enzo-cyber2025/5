package app.arenatech.localai

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import app.arenatech.localai.data.ModelSlots
import app.arenatech.localai.data.ModelStore
import app.arenatech.localai.ui.ModelAdapter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ModelsActivity : AppCompatActivity() {

    private lateinit var list: RecyclerView
    private lateinit var adapter: ModelAdapter
    private var pendingSlot: String? = null

    private val picker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { handleImport(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_models)

        val toolbar: Toolbar = findViewById(R.id.toolbar)
        toolbar.setNavigationOnClickListener { finish() }

        list = findViewById(R.id.list)
        list.layoutManager = LinearLayoutManager(this)
        adapter = ModelAdapter(
            items = snapshotSlots(),
            onImport = { slotId ->
                pendingSlot = slotId
                picker.launch(arrayOf("*/*"))
            },
            onRemove = { slotId ->
                lifecycleScope.launch(Dispatchers.IO) {
                    ModelStore.instance.clear(slotId)
                }
                Toast.makeText(this, "Modelo removido", Toast.LENGTH_SHORT).show()
            },
        )
        list.adapter = adapter

        // Keep the list fresh whenever a slot changes.
        lifecycleScope.launch {
            ModelStore.instance.slots.collect { refresh() }
        }
    }

    private fun snapshotSlots() = ModelSlots.allIds.map { ModelStore.instance.slots.value[it] ?: ModelStore.instance.emptySlot(it) }

    private fun refresh() {
        val newItems = snapshotSlots()
        adapter = ModelAdapter(
            items = newItems,
            onImport = { slotId -> pendingSlot = slotId; picker.launch(arrayOf("*/*")) },
            onRemove = { slotId ->
                lifecycleScope.launch(Dispatchers.IO) { ModelStore.instance.clear(slotId) }
                Toast.makeText(this, "Modelo removido", Toast.LENGTH_SHORT).show()
            },
        )
        list.adapter = adapter
        adapter.notifyDataSetChanged()
    }

    private fun handleImport(uri: Uri) {
        val slotId = pendingSlot
        if (slotId == null) { Toast.makeText(this, "Nenhum espaço selecionado", Toast.LENGTH_SHORT).show(); return }
        Toast.makeText(this, "Importando GGUF… (modelos grandes demoram)", Toast.LENGTH_LONG).show()
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val slot = ModelStore.instance.importTo(slotId, uri)
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@ModelsActivity, "Importado: ${slot.sourceName}", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@ModelsActivity, "Falha ao importar: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    companion object {
        fun start(activity: AppCompatActivity) {
            activity.startActivity(Intent(activity, ModelsActivity::class.java))
        }
    }
}
