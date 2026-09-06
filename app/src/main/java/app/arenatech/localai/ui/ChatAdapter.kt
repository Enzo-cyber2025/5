package app.arenatech.localai.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import app.arenatech.localai.R
import app.arenatech.localai.data.ChatStore

/** Renders the list of chats in the drawer. */
class ChatAdapter(
    private val items: List<ChatStore.ChatMeta>,
    private val slotLabel: (String) -> String,
    private val onOpen: (String) -> Unit,
    private val onDelete: (String) -> Unit,
    private val onAssignModel: (String) -> Unit,
) : RecyclerView.Adapter<ChatAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val title: TextView = view.findViewById(R.id.title)
        val preview: TextView = view.findViewById(R.id.preview)
        val modelTag: TextView = view.findViewById(R.id.modelTag)
        val deleteBtn: ImageButton = view.findViewById(R.id.deleteBtn)
        val row: View = view.findViewById(R.id.row)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_chat, parent, false))

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val it = items[position]
        holder.title.text = it.title
        holder.preview.text = it.preview.ifEmpty { "Conversa vazia" }
        holder.modelTag.text = slotLabel(it.modelSlotId)
        holder.row.setOnClickListener { onOpen(it.id) }
        holder.row.setOnLongClickListener { onAssignModel(it.id); true }
        holder.deleteBtn.setOnClickListener { onDelete(it.id) }
    }
}
