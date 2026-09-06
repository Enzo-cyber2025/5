package app.arenatech.localai.ui

import android.graphics.BitmapFactory
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import app.arenatech.localai.R
import app.arenatech.localai.data.Msg
import app.arenatech.localai.data.Roles
import java.io.File

/**
 * Renders the message list of the open chat. Also renders a collapsible
 * "thinking" block on assistant messages produced by the thinking tool.
 */
class MessageAdapter(
    private var messages: List<Msg> = emptyList(),
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    private var expandedThinking = HashSet<String>()

    companion object {
        private const val V_USER = 0
        private const val V_ASSISTANT = 1
        private const val V_SYSTEM = 2
    }

    fun update(list: List<Msg>) {
        // cheap identity check to avoid needless notifies per token
        if (list === messages) return
        val prevSize = messages.size
        messages = list
        if (prevSize != list.size) notifyDataSetChanged()
        else {
            notifyItemRangeChanged(0, list.size)
        }
        // prune removed ids
        if (expandedThinking.isNotEmpty()) {
            val ids = list.mapTo(HashSet()) { it.id }
            expandedThinking.removeIf { it !in ids }
        }
    }

    override fun getItemViewType(position: Int): Int = when (messages[position].role) {
        Roles.USER -> V_USER
        Roles.ASSISTANT -> V_ASSISTANT
        else -> V_SYSTEM
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return when (viewType) {
            V_USER -> UserVH(inflater.inflate(R.layout.item_user, parent, false))
            V_SYSTEM -> SystemVH(inflater.inflate(R.layout.item_system, parent, false))
            else -> AssistantVH(inflater.inflate(R.layout.item_assistant, parent, false))
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        val msg = messages[position]
        when (holder) {
            is UserVH -> holder.bind(msg)
            is SystemVH -> holder.bind(msg.text)
            is AssistantVH -> holder.bind(msg, position)
        }
    }

    override fun getItemCount(): Int = messages.size

    class UserVH(view: View) : RecyclerView.ViewHolder(view) {
        private val text: TextView = view.findViewById(R.id.text)
        private val img: ImageView = view.findViewById(R.id.img)
        fun bind(msg: Msg) {
            text.text = msg.text
            val p = msg.imagePath
            if (p != null && File(p).exists()) {
                val bmp = decodeSampled(File(p))
                if (bmp != null) { img.setImageBitmap(bmp); img.visibility = View.VISIBLE }
                else img.visibility = View.GONE
            } else {
                img.visibility = View.GONE
            }
        }
    }

    inner class AssistantVH(view: View) : RecyclerView.ViewHolder(view) {
        private val text: TextView = view.findViewById(R.id.text)
        private val thinkHeader: TextView = view.findViewById(R.id.thinkHeader)
        private val thinkBody: TextView = view.findViewById(R.id.thinkBody)
        fun bind(msg: Msg, pos: Int) {
            val t = msg.text
            text.text = t.ifEmpty {
                if (msg.thinking.isNotBlank()) "" else "…"
            }
            val hasThink = msg.thinking.isNotBlank()
            if (hasThink) {
                thinkHeader.visibility = View.VISIBLE
                thinkBody.text = msg.thinking
                val expanded = expandedThinking.contains(msg.id)
                thinkBody.visibility = if (expanded) View.VISIBLE else View.GONE
                thinkHeader.setOnClickListener {
                    if (expanded) expandedThinking.remove(msg.id) else expandedThinking.add(msg.id)
                    notifyItemChanged(adapterPosition)
                }
            } else {
                thinkHeader.visibility = View.GONE
                thinkBody.visibility = View.GONE
            }
        }
    }

    class SystemVH(view: View) : RecyclerView.ViewHolder(view) {
        private val text: TextView = view.findViewById(R.id.text)
        fun bind(t: String) { text.text = t }
    }

    private fun decodeSampled(file: File, target: Int = 512): android.graphics.Bitmap? {
        return try {
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.absolutePath, opts)
            var sample = 1
            while (opts.outWidth / sample > target * 2 || opts.outHeight / sample > target * 2) sample *= 2
            val o = BitmapFactory.Options().apply { inSampleSize = sample }
            BitmapFactory.decodeFile(file.absolutePath, o)
        } catch (e: Exception) { null }
    }
}
