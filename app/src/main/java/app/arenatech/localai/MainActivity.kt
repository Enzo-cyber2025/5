package app.arenatech.localai

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.ActionBarDrawerToggle
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.core.app.ActivityCompat
import androidx.drawerlayout.widget.DrawerLayout
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import app.arenatech.localai.data.ChatStore
import app.arenatech.localai.data.ModelSlots
import app.arenatech.localai.data.ModelStore
import app.arenatech.localai.data.Prefs
import app.arenatech.localai.data.Roles
import app.arenatech.localai.engine.Engine
import app.arenatech.localai.generation.GenerationRunner
import app.arenatech.localai.service.GenerationService
import app.arenatech.localai.ui.ChatAdapter
import app.arenatech.localai.ui.MessageAdapter
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.google.android.material.floatingactionbutton.FloatingActionButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

class MainActivity : AppCompatActivity() {

    private lateinit var drawer: DrawerLayout
    private lateinit var toolbar: Toolbar
    private lateinit var toggle: ActionBarDrawerToggle
    private lateinit var messagesRv: RecyclerView
    private lateinit var emptyHint: TextView
    private lateinit var chipGroup: ChipGroup
    private lateinit var thinkChip: Chip
    private lateinit var researchChip: Chip
    private lateinit var attachBtn: ImageButton
    private lateinit var input: EditText
    private lateinit var sendFab: FloatingActionButton
    private lateinit var lockedHint: TextView
    private lateinit var chatListRv: RecyclerView
    private lateinit var openModelsRow: View

    private var activeChatId: String? = null
    private var pendingImagePath: String? = null

    private val messageAdapter = MessageAdapter()
    private var chatAdapter: ChatAdapter? = null

    private val imagePicker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { storeImage(it) }
    }
    private val notifPerm = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) {
            // Foreground-service notification simply won't show on some OEMs; generation still runs.
            Toast.makeText(this, "Permita notificações para ver o progresso com a tela bloqueada", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        drawer = findViewById(R.id.drawer)
        toolbar = findViewById(R.id.toolbar)
        messagesRv = findViewById(R.id.messages)
        emptyHint = findViewById(R.id.emptyHint)
        chipGroup = findViewById(R.id.chipGroup)
        thinkChip = findViewById(R.id.thinkChip)
        researchChip = findViewById(R.id.researchChip)
        attachBtn = findViewById(R.id.attachBtn)
        input = findViewById(R.id.input)
        sendFab = findViewById(R.id.sendFab)
        lockedHint = findViewById(R.id.lockedHint)
        chatListRv = findViewById(R.id.chatList)
        openModelsRow = findViewById(R.id.openModelsRow)

        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayShowTitleEnabled(false)

        toggle = ActionBarDrawerToggle(this, drawer, toolbar, 0, 0)
        drawer.addDrawerListener(toggle)
        toggle.syncState()

        messagesRv.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        messagesRv.adapter = messageAdapter
        chatListRv.layoutManager = LinearLayoutManager(this)

        // chips reflect + persist prefs
        thinkChip.isChecked = Prefs.instance.thinkingEnabled
        researchChip.isChecked = Prefs.instance.researchEnabled
        thinkChip.setOnCheckedChangeListener { _, c -> Prefs.instance.thinkingEnabled = c }
        researchChip.setOnCheckedChangeListener { _, c -> Prefs.instance.researchEnabled = c }
        lockedHint.visibility = if (Prefs.instance.generateWithScreenLocked) View.VISIBLE else View.GONE
        lockedHint.setOnClickListener { showSettingsDialog() }

        sendFab.setOnClickListener { onSend() }
        input.setOnEditorActionListener { _, _, _ -> onSend(); true }
        attachBtn.setOnClickListener { imagePicker.launch("image/*") }
        openModelsRow.setOnClickListener { drawer.closeDrawers(); ModelsActivity.start(this) }

        findViewById<ImageButton>(R.id.newChatBtn).setOnClickListener { newChat() }

        // Load active chat (from intent or persisted first).
        val openId = intent?.getStringExtra(EXTRA_OPEN_CHAT) ?: ChatStore.instance.firstOrNew().id
        openChat(openId)

        // Observe chat store for any change (streaming from the service included).
        lifecycleScope.launch {
            ChatStore.instance.revision.collectLatest {
                refreshChatList()
                refreshMessages()
            }
        }
        // Observe model slots to refresh drawer labels.
        lifecycleScope.launch {
            ModelStore.instance.slots.collect { refreshChatList(); updateTitleAndSubtitle() }
        }
        // Observe generation runner status to enable/disable composer.
        lifecycleScope.launch {
            GenerationRunner.status.collect { s ->
                val running = s.phase == GenerationRunner.Phase.LOADING || s.phase == GenerationRunner.Phase.GENERATING
                updateComposer(running)
                updateTitleAndSubtitle()
            }
        }
    }

    // ---------------------------------------------------------------- drawer / chat switching

    private fun refreshChatList() {
        val items = ChatStore.instance.listMeta()
        if (items.isEmpty()) {
            ChatStore.instance.createChat("Novo chat", ModelSlots.DEFAULT_SLOT_ID)
            return
        }
        chatAdapter = ChatAdapter(
            items = items,
            slotLabel = { slotId ->
                ModelStore.instance.slots.value[slotId]?.sourceName
                    ?.substringBefore(" ")
                    ?.take(8)
                    ?: slotId.removePrefix("slot-").let { "M${it.toInt() + 1}" }
            },
            onOpen = { id -> drawer.closeDrawers(); openChat(id) },
            onDelete = { id -> confirmDelete(id) },
            onAssignModel = { id -> showModelPicker(id) },
        )
        chatListRv.adapter = chatAdapter
    }

    private fun openChat(id: String) {
        val chat = ChatStore.instance.get(id) ?: return
        activeChatId = id
        updateTitleAndSubtitle()
        refreshMessages()
    }

    private fun newChat() {
        val box = EditText(this)
        box.hint = "Nome da conversa"
        AlertDialog.Builder(this)
            .setTitle("Nova conversa")
            .setView(box)
            .setPositiveButton("Criar") { _, _ ->
                val c = ChatStore.instance.createChat(box.text.toString(), ModelSlots.DEFAULT_SLOT_ID)
                openChat(c.id)
                refreshChatList()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun confirmDelete(id: String) {
        AlertDialog.Builder(this)
            .setTitle("Excluir conversa?")
            .setMessage("Esta ação não pode ser desfeita.")
            .setPositiveButton("Excluir") { _, _ ->
                ChatStore.instance.deleteChat(id)
                if (activeChatId == id) {
                    activeChatId = null
                    openChat(ChatStore.instance.firstOrNew().id)
                }
                refreshChatList()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showModelPicker(chatId: String) {
        val slotIds = ModelSlots.allIds
        val names = slotIds.map { id ->
            val s = ModelStore.instance.slots.value[id]
            val base = if (id == ModelSlots.DEFAULT_SLOT_ID) "Modelo 1" else "Modelo 2"
            if (s?.isEmpty == false) "$base — ${s.sourceName}" else "$base — vazio"
        }.toTypedArray()
        val current = slotIds.indexOf(ChatStore.instance.get(chatId)?.modelSlotId).coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle("Modelo desta conversa")
            .setSingleChoiceItems(names, current) { d, which ->
                ChatStore.instance.setModelSlot(chatId, slotIds[which])
                if (activeChatId == chatId) updateTitleAndSubtitle()
                refreshChatList()
                d.dismiss()
            }
            .setNeutralButton("Gerenciar modelos") { _, _ -> ModelsActivity.start(this) }
            .show()
    }

    // ---------------------------------------------------------------- rendering

    private fun updateTitleAndSubtitle() {
        val chat = activeChatId?.let { ChatStore.instance.get(it) }
        if (chat == null) { toolbar.title = ""; toolbar.subtitle = ""; return }
        toolbar.title = chat.title
        val slot = ModelStore.instance.slots.value[chat.modelSlotId]
        val modelName = if (slot?.isEmpty == false) slot.sourceName else "sem modelo"
        val running = GenerationRunner.isRunning
        toolbar.subtitle = "$modelName${if (running) " · gerando…" else ""}"
    }

    private fun refreshMessages() {
        val id = activeChatId
        if (id == null) return
        val snap = ChatStore.instance.snapshot(id)
        messageAdapter.update(snap)
        emptyHint.visibility = if (snap.isEmpty()) View.VISIBLE else View.GONE
        if (snap.isNotEmpty()) {
            messagesRv.post {
                messagesRv.scrollToPosition(messageAdapter.itemCount - 1)
            }
        }
    }

    private fun updateComposer(running: Boolean) {
        sendFab.isEnabled = !running
        input.isEnabled = !running
    }

    // ---------------------------------------------------------------- sending

    private fun onSend(): Boolean {
        if (GenerationRunner.isRunning) { Toast.makeText(this, "Aguarde a resposta terminar", Toast.LENGTH_SHORT).show(); return false }
        val chatId = activeChatId ?: return false
        val chat = ChatStore.instance.get(chatId) ?: return false
        val slot = ModelStore.instance.slots.value[chat.modelSlotId]
        if (slot?.isEmpty != false) {
            Toast.makeText(this, "Este chat não tem modelo. Importe um GGUF.", Toast.LENGTH_LONG).show()
            ModelsActivity.start(this)
            return false
        }
        val text = input.text.toString().trim()
        if (text.isEmpty() && pendingImagePath == null) return false
        if (text.isEmpty()) {
            Toast.makeText(this, "Anexe também uma mensagem de texto.", Toast.LENGTH_SHORT).show()
            return false
        }
        // If an image is attached, record it, but be explicit that the on-device
        // engine currently processes only the text prompt.
        val img = pendingImagePath
        pendingImagePath = null
        ChatStore.instance.addUserMessage(chatId, text, img)
        if (img != null) {
            ChatStore.instance.addSystem(chatId, "🖼 Imagem anexada (exibida acima). O modelo local neste APK processa apenas o texto da mensagem.")
        }
        input.text = null
        requestNotifIfNeeded()

        val research = researchChip.isChecked
        val thinking = thinkChip.isChecked
        GenerationService.start(this, chatId, research, thinking)
        return true
    }

    private fun requestNotifIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    // ---------------------------------------------------------------- image attach

    private fun storeImage(uri: Uri) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val dir = File(filesDir, "attachments").apply { mkdirs() }
                val dest = File(dir, "${UUID.randomUUID().toString()}.img")
                contentResolver.openInputStream(uri)?.use { input ->
                    dest.outputStream().use { out -> input.copyTo(out) }
                }
                pendingImagePath = dest.absolutePath
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "Imagem anexada", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "Falha ao anexar: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    // ---------------------------------------------------------------- menus / settings

    override fun onCreateOptionsMenu(menu: Menu?): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_models -> { ModelsActivity.start(this); true }
            R.id.action_settings -> { showSettingsDialog(); true }
            R.id.action_assign_model -> {
                activeChatId?.let { showModelPicker(it) }
                true
            }
            R.id.action_clear_context -> {
                lifecycleScope.launch(Dispatchers.IO) {
                    GenerationRunner.stopAndJoin()
                    Engine.unloadSync()
                }
                Toast.makeText(this, "Contexto do modelo recarregado (memória esvaziada)", Toast.LENGTH_SHORT).show()
                true
            }
            R.id.action_about -> { showAbout(); true }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun showSettingsDialog() {
        val views = layoutInflater.inflate(R.layout.dialog_settings, null)
        val think = views.findViewById<Chip>(R.id.dThink)
        val research = views.findViewById<Chip>(R.id.dResearch)
        val locked = views.findViewById<Chip>(R.id.dLocked)
        val predict = views.findViewById<EditText>(R.id.dPredict)
        val persona = views.findViewById<EditText>(R.id.dPersona)
        think.isChecked = Prefs.instance.thinkingEnabled
        research.isChecked = Prefs.instance.researchEnabled
        locked.isChecked = Prefs.instance.generateWithScreenLocked
        predict.setText(Prefs.instance.predictTokens.toString())
        persona.setText(Prefs.instance.persona)
        AlertDialog.Builder(this)
            .setTitle("Configurações")
            .setView(views)
            .setPositiveButton("Salvar") { _, _ ->
                Prefs.instance.thinkingEnabled = think.isChecked
                Prefs.instance.researchEnabled = research.isChecked
                Prefs.instance.generateWithScreenLocked = locked.isChecked
                Prefs.instance.predictTokens = predict.text.toString().toIntOrNull() ?: 512
                Prefs.instance.persona = persona.text.toString().ifBlank { Prefs.DEFAULT_PERSONA }
                thinkChip.isChecked = think.isChecked
                researchChip.isChecked = research.isChecked
                lockedHint.visibility = if (locked.isChecked) View.VISIBLE else View.GONE
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showAbout() {
        AlertDialog.Builder(this)
            .setTitle("LocalAI")
            .setMessage(
                "• Importe arquivos GGUF que estão na memória do aparelho (2 espaços de modelo).\n" +
                    "• A inferência usa o backend nativo do llama.cpp — Vulkan (GPU) quando disponível, com CPU como reserva.\n" +
                    "• Cada conversa usa um modelo e guarda seu histórico.\n" +
                    "• Ative “Pensar” para o modelo raciocinar antes da resposta e “Pesquisar na web” para buscar contexto antes de responder.\n" +
                    "• As respostas continuam gerando com a tela bloqueada (serviço em primeiro plano).\n" +
                    "• Limitação: imagens anexadas são exibidas, mas o motor embarcado processa somente texto."
            )
            .setPositiveButton("OK", null)
            .show()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_OPEN_CHAT)?.let { openChat(it) }
    }

    override fun onStop() {
        ChatStore.instance.persistNow()
        super.onStop()
    }

    companion object {
        const val EXTRA_OPEN_CHAT = "open_chat"
    }
}
