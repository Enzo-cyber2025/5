package app.arenatech.localai.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.button.MaterialButton
import app.arenatech.localai.R
import app.arenatech.localai.data.ModelSlot

class ModelAdapter(
    private val items: List<ModelSlot>,
    private val onImport: (String) -> Unit,
    private val onRemove: (String) -> Unit,
) : RecyclerView.Adapter<ModelAdapter.VH>() {

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val title: TextView = view.findViewById(R.id.title)
        val detail: TextView = view.findViewById(R.id.detail)
        val meta: TextView = view.findViewById(R.id.meta)
        val importBtn: MaterialButton = view.findViewById(R.id.importBtn)
        val removeBtn: MaterialButton = view.findViewById(R.id.removeBtn)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_model, parent, false))

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val s = items[position]
        holder.title.text = s.label
        if (s.isEmpty) {
            holder.detail.text = holder.itemView.context.getString(R.string.slot_no_model)
            holder.removeBtn.isEnabled = false
            holder.meta.visibility = View.GONE
            holder.importBtn.text = holder.itemView.context.getString(R.string.import_model)
        } else {
            val ctx = holder.itemView.context
            val v = if (s.vision) " · 🖼 multimodal" else ""
            holder.detail.text = "${s.sourceName}\n${s.arch} · ${s.sizeLabel}$v"
            holder.meta.text = s.metaSummary
            holder.meta.visibility = View.VISIBLE
            holder.removeBtn.isEnabled = true
            holder.importBtn.text = ctx.getString(R.string.import_model)
        }
        holder.importBtn.setOnClickListener { onImport(s.id) }
        holder.removeBtn.setOnClickListener { onRemove(s.id) }
    }
}
