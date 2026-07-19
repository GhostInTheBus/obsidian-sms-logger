package com.vi.assist

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.floatingactionbutton.FloatingActionButton

class WhitelistActivity : AppCompatActivity() {

    private lateinit var adapter: WhitelistAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_whitelist)
        setSupportActionBar(findViewById(R.id.toolbar))
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        adapter = WhitelistAdapter(loadNumbers()) { number ->
            val updated = loadNumbers().toMutableSet().also { it.remove(number) }
            Prefs.saveWhitelist(this, updated)
            adapter.update(updated.toSortedSet())
        }

        findViewById<RecyclerView>(R.id.rvWhitelist).apply {
            layoutManager = LinearLayoutManager(this@WhitelistActivity)
            adapter = this@WhitelistActivity.adapter
        }

        findViewById<FloatingActionButton>(R.id.fabAdd).setOnClickListener {
            showAddDialog()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }

    private fun loadNumbers() = Prefs.whitelist(this)

    private fun showAddDialog() {
        val input = EditText(this).apply {
            hint = getString(R.string.whitelist_hint)
            inputType = android.text.InputType.TYPE_CLASS_PHONE
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.add_number)
            .setView(input)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val raw = input.text.toString().trim()
                if (raw.isNotEmpty()) {
                    val normalized = raw.filter { it.isDigit() }.trimStart('1')
                    if (normalized.isNotEmpty()) {
                        val updated = loadNumbers().toMutableSet().also { it.add(normalized) }
                        Prefs.saveWhitelist(this, updated)
                        adapter.update(updated.toSortedSet())
                    }
                }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    class WhitelistAdapter(
        private var items: Collection<String>,
        private val onDelete: (String) -> Unit
    ) : RecyclerView.Adapter<WhitelistAdapter.VH>() {

        fun update(newItems: Collection<String>) {
            items = newItems
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_whitelist_number, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val number = items.toList()[position]
            holder.tvNumber.text = number
            holder.btnDelete.setOnClickListener { onDelete(number) }
        }

        override fun getItemCount() = items.size

        class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvNumber: TextView = view.findViewById(R.id.tvNumber)
            val btnDelete: ImageButton = view.findViewById(R.id.btnDelete)
        }
    }
}
