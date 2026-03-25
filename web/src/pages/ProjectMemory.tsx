import { useState } from 'react';
import { Save, Plus, Brain, X } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { useProjectMemory, useUpdateMemory, useAddMemoryNote } from '../lib/api';
import { toastSuccess, toastError } from '../lib/toast';
import type { ProjectMemorySection } from '../lib/types';

const sectionIcons: Record<string, string> = {
  agent_identity: 'Agent Identity',
  business_constraints: 'Business Constraints',
  known_good_patterns: 'Known Good Patterns',
  known_bad_patterns: 'Known Bad Patterns',
  team_preferences: 'Team Preferences',
  optimization_history: 'Optimization History',
};

function SectionCard({
  section,
  onContentChange,
  onAddNote,
  isAddingNote,
}: {
  section: ProjectMemorySection;
  onContentChange: (key: string, content: string) => void;
  onAddNote: (key: string, note: string) => void;
  isAddingNote: boolean;
}) {
  const [noteText, setNoteText] = useState('');
  const [showNoteInput, setShowNoteInput] = useState(false);

  function handleSubmitNote() {
    if (!noteText.trim()) return;
    onAddNote(section.key, noteText.trim());
    setNoteText('');
    setShowNoteInput(false);
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">
          {sectionIcons[section.key] ?? section.title}
        </h3>
        <button
          onClick={() => setShowNoteInput(!showNoteInput)}
          className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600 transition hover:bg-gray-50"
        >
          <Plus className="h-3 w-3" />
          Add Note
        </button>
      </div>

      <textarea
        value={section.content}
        onChange={(e) => onContentChange(section.key, e.target.value)}
        rows={4}
        className="w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none"
      />

      {/* Notes list */}
      {section.notes.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <h4 className="text-[11px] font-medium text-gray-400">Notes</h4>
          {section.notes.map((note, i) => (
            <div
              key={i}
              className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-700"
            >
              {note}
            </div>
          ))}
        </div>
      )}

      {/* Add note input */}
      {showNoteInput && (
        <div className="mt-3 flex items-center gap-2">
          <input
            type="text"
            placeholder="Enter a note..."
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmitNote();
            }}
            className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleSubmitNote}
            disabled={!noteText.trim() || isAddingNote}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          >
            Add
          </button>
          <button
            onClick={() => setShowNoteInput(false)}
            className="rounded-md border border-gray-200 p-1.5 text-gray-400 hover:bg-gray-50 hover:text-gray-600"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

export function ProjectMemory() {
  const { data: memory, isLoading, isError } = useProjectMemory();
  const updateMutation = useUpdateMemory();
  const addNoteMutation = useAddMemoryNote();

  const [localSections, setLocalSections] = useState<ProjectMemorySection[] | null>(null);
  const [dirty, setDirty] = useState(false);

  // Initialize local state from fetched data
  const sections = localSections ?? memory?.sections ?? [];

  function handleContentChange(key: string, content: string) {
    const updated = sections.map((s) =>
      s.key === key ? { ...s, content } : s
    );
    setLocalSections(updated);
    setDirty(true);
  }

  function handleSave() {
    if (!memory) return;
    updateMutation.mutate(
      { sections, updated_at: memory.updated_at },
      {
        onSuccess: () => {
          toastSuccess('Memory saved', 'Project memory has been updated.');
          setDirty(false);
        },
        onError: (error) => {
          toastError('Save failed', error.message);
        },
      }
    );
  }

  function handleAddNote(sectionKey: string, note: string) {
    if (!note) return;

    addNoteMutation.mutate(
      { section: sectionKey, note },
      {
        onSuccess: () => {
          toastSuccess('Note added', `Note added to ${sectionKey}.`);
          // Update local state to show the note immediately
          const updated = sections.map((s) =>
            s.key === sectionKey ? { ...s, notes: [...s.notes, note] } : s
          );
          setLocalSections(updated);
        },
        onError: (error) => {
          toastError('Add note failed', error.message);
        },
      }
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Project Memory"
        description="View and edit your AUTOAGENT.md project memory — identity, constraints, patterns, and preferences"
        actions={
          <button
            onClick={handleSave}
            disabled={!dirty || updateMutation.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            <Save className="h-4 w-4" />
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        }
      />

      {/* Loading / error */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading project memory...
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load project memory.
        </div>
      )}

      {/* Section cards */}
      {!isLoading && !isError && (
        <>
          {sections.length === 0 ? (
            <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              <div className="text-center">
                <Brain className="mx-auto mb-2 h-8 w-8 text-gray-400" />
                <p>No project memory found.</p>
                <p className="mt-1 text-xs text-gray-400">Create an AUTOAGENT.md file to get started.</p>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {sections.map((section) => (
                <SectionCard
                  key={section.key}
                  section={section}
                  onContentChange={handleContentChange}
                  onAddNote={handleAddNote}
                  isAddingNote={addNoteMutation.isPending}
                />
              ))}
            </div>
          )}

          {dirty && (
            <div className="rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
              You have unsaved changes.
            </div>
          )}
        </>
      )}
    </div>
  );
}
