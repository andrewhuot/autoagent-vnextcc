import { useCallback, useState } from 'react';
import { Upload, X, File, FileText, FileAudio, FileArchive, Loader2 } from 'lucide-react';
import { classNames } from '../../lib/utils';
import { useUploadFile } from '../../lib/assistant-api';
import type { UploadedFile } from '../../lib/types';

interface FileUploadProps {
  onFilesUploaded: (files: UploadedFile[]) => void;
  maxFiles?: number;
  acceptedTypes?: string[];
}

const ACCEPTED_TYPES = {
  'text/csv': ['.csv'],
  'application/json': ['.json', '.jsonl'],
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'application/zip': ['.zip'],
  'audio/mpeg': ['.mp3'],
  'audio/wav': ['.wav'],
  'audio/x-m4a': ['.m4a'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/yaml': ['.yaml', '.yml'],
};

function getFileIcon(type: string) {
  if (type.startsWith('audio/')) return FileAudio;
  if (type === 'application/zip') return FileArchive;
  if (type === 'application/pdf' || type.startsWith('text/')) return FileText;
  return File;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileUpload({ onFilesUploaded, maxFiles = 5, acceptedTypes }: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState<Set<string>>(new Set());
  const uploadFile = useUploadFile();

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setIsDragging(false);
  }, []);

  const processFiles = useCallback(
    async (fileList: FileList) => {
      const newFiles = Array.from(fileList).slice(0, maxFiles - files.length);

      for (const file of newFiles) {
        // Check file type
        const acceptedTypeList = acceptedTypes || Object.keys(ACCEPTED_TYPES);
        const isAccepted = acceptedTypeList.some((type) => file.type === type || file.name.endsWith(type));

        if (!isAccepted) {
          console.warn(`File type ${file.type} not accepted for ${file.name}`);
          continue;
        }

        // Add to uploading set
        setUploadingFiles((prev) => new Set([...prev, file.name]));

        try {
          const uploadedFile = await uploadFile.mutateAsync(file);
          setFiles((prev) => [...prev, uploadedFile]);
          setUploadingFiles((prev) => {
            const next = new Set(prev);
            next.delete(file.name);
            return next;
          });
        } catch (error) {
          console.error('Upload failed:', error);
          setUploadingFiles((prev) => {
            const next = new Set(prev);
            next.delete(file.name);
            return next;
          });
        }
      }
    },
    [files.length, maxFiles, acceptedTypes, uploadFile]
  );

  const handleDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();
      setIsDragging(false);

      const fileList = event.dataTransfer.files;
      if (fileList.length > 0) {
        await processFiles(fileList);
      }
    },
    [processFiles]
  );

  const handleFileSelect = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const fileList = event.target.files;
      if (fileList && fileList.length > 0) {
        await processFiles(fileList);
      }
      event.target.value = '';
    },
    [processFiles]
  );

  const removeFile = useCallback(
    (index: number) => {
      const newFiles = files.filter((_, i) => i !== index);
      setFiles(newFiles);
      onFilesUploaded(newFiles);
    },
    [files, onFilesUploaded]
  );

  const acceptString = acceptedTypes?.join(',') || Object.values(ACCEPTED_TYPES).flat().join(',');

  return (
    <div className="space-y-3">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={classNames(
          'relative rounded-lg border-2 border-dashed p-6 text-center transition',
          isDragging
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100'
        )}
      >
        <input
          type="file"
          id="file-upload"
          multiple
          accept={acceptString}
          onChange={handleFileSelect}
          className="hidden"
          disabled={files.length >= maxFiles}
        />

        <label
          htmlFor="file-upload"
          className={classNames(
            'cursor-pointer',
            files.length >= maxFiles ? 'cursor-not-allowed opacity-50' : ''
          )}
        >
          <Upload className="mx-auto h-8 w-8 text-gray-400" />
          <p className="mt-2 text-sm text-gray-600">
            {isDragging ? (
              <span className="font-medium text-blue-600">Drop files here</span>
            ) : (
              <>
                <span className="font-medium text-blue-600">Click to upload</span> or drag and drop
              </>
            )}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            CSV, JSON, PDF, TXT, ZIP, Audio files ({maxFiles - files.length} remaining)
          </p>
        </label>
      </div>

      {(files.length > 0 || uploadingFiles.size > 0) && (
        <div className="space-y-2">
          {files.map((file, index) => {
            const Icon = getFileIcon(file.type);
            return (
              <div
                key={index}
                className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <Icon className="h-5 w-5 text-gray-400" />
                  <div>
                    <p className="text-sm font-medium text-gray-900">{file.name}</p>
                    <p className="text-xs text-gray-500">{formatFileSize(file.size)}</p>
                  </div>
                </div>
                <button
                  onClick={() => removeFile(index)}
                  className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            );
          })}

          {Array.from(uploadingFiles).map((fileName) => (
            <div
              key={fileName}
              className="flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-3 py-2"
            >
              <div className="flex items-center gap-3">
                <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
                <div>
                  <p className="text-sm font-medium text-blue-900">{fileName}</p>
                  <p className="text-xs text-blue-600">Uploading...</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
