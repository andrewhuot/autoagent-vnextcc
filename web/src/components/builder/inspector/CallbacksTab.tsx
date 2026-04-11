export function CallbacksTab() {
  return (
    <div className="rounded-md border border-slate-700 bg-slate-900/70 p-4">
      <p className="mb-2 text-xs font-semibold text-slate-200">Callbacks</p>
      <p className="text-[11px] text-slate-500">
        Custom callback hooks (before_model, after_tool, etc.) coming soon. For MVP, callbacks are
        configured via the system prompt.
      </p>
    </div>
  );
}
