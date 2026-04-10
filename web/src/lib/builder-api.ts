import type {
  ApprovalRequest,
  ApprovalResponseRequest,
  ArtifactCommentRequest,
  ArtifactRef,
  ArtifactType,
  BuilderEvent,
  BuilderMetricsSnapshot,
  BuilderProject,
  BuilderProposal,
  BuilderSession,
  BuilderTask,
  CreateProjectRequest,
  CreateSessionRequest,
  CreateTaskRequest,
  PermissionGrant,
  PermissionGrantRequest,
  SpecialistDefinition,
  SpecialistInvokeRequest,
  TaskProgressRequest,
  UpdateProjectRequest,
} from './builder-types';

export class BuilderApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'BuilderApiError';
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/builder${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const fallback = response.status >= 500
      ? 'The server is temporarily unavailable. Retrying usually resolves this.'
      : 'Something went wrong with the request. Try again or check Setup.';
    let message = fallback;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      message = payload.detail || payload.message || fallback;
    } catch {
      const text = await response.text().catch(() => '');
      message = (text && text.trim()) ? text : fallback;
    }
    throw new BuilderApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const builderApi = {
  projects: {
    list(archived = false): Promise<BuilderProject[]> {
      return request(`/projects?archived=${archived ? 'true' : 'false'}`);
    },
    create(payload: CreateProjectRequest): Promise<BuilderProject> {
      return request('/projects', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    get(projectId: string): Promise<BuilderProject> {
      return request(`/projects/${projectId}`);
    },
    update(projectId: string, payload: UpdateProjectRequest): Promise<BuilderProject> {
      return request(`/projects/${projectId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
    },
    async delete(projectId: string): Promise<boolean> {
      const response = await request<{ deleted: boolean }>(`/projects/${projectId}`, {
        method: 'DELETE',
      });
      return response.deleted;
    },
  },

  sessions: {
    list(projectId?: string): Promise<BuilderSession[]> {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
      return request(`/sessions${suffix}`);
    },
    create(payload: CreateSessionRequest): Promise<BuilderSession> {
      return request('/sessions', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    get(sessionId: string): Promise<BuilderSession> {
      return request(`/sessions/${sessionId}`);
    },
    close(sessionId: string): Promise<BuilderSession> {
      return request(`/sessions/${sessionId}/close`, {
        method: 'POST',
      });
    },
  },

  tasks: {
    list(params?: { sessionId?: string; projectId?: string; status?: string }): Promise<BuilderTask[]> {
      const query = new URLSearchParams();
      if (params?.sessionId) query.set('session_id', params.sessionId);
      if (params?.projectId) query.set('project_id', params.projectId);
      if (params?.status) query.set('status', params.status);
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return request(`/tasks${suffix}`);
    },
    create(payload: CreateTaskRequest): Promise<BuilderTask> {
      return request('/tasks', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    get(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}`);
    },
    pause(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/pause`, { method: 'POST' });
    },
    resume(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/resume`, { method: 'POST' });
    },
    cancel(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/cancel`, { method: 'POST' });
    },
    duplicate(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/duplicate`, { method: 'POST' });
    },
    fork(taskId: string): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/fork`, { method: 'POST' });
    },
    progress(taskId: string, payload: TaskProgressRequest): Promise<BuilderTask> {
      return request(`/tasks/${taskId}/progress`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
  },

  proposals: {
    list(taskId?: string): Promise<BuilderProposal[]> {
      const suffix = taskId ? `?task_id=${encodeURIComponent(taskId)}` : '';
      return request(`/proposals${suffix}`);
    },
    get(proposalId: string): Promise<BuilderProposal> {
      return request(`/proposals/${proposalId}`);
    },
    approve(proposalId: string): Promise<BuilderProposal> {
      return request(`/proposals/${proposalId}/approve`, { method: 'POST' });
    },
    reject(proposalId: string): Promise<BuilderProposal> {
      return request(`/proposals/${proposalId}/reject`, { method: 'POST' });
    },
    revise(proposalId: string, comment: string): Promise<BuilderProposal> {
      return request(`/proposals/${proposalId}/revise`, {
        method: 'POST',
        body: JSON.stringify({ comment }),
      });
    },
  },

  artifacts: {
    list(params?: { taskId?: string; sessionId?: string; artifactType?: ArtifactType }): Promise<ArtifactRef[]> {
      const query = new URLSearchParams();
      if (params?.taskId) query.set('task_id', params.taskId);
      if (params?.sessionId) query.set('session_id', params.sessionId);
      if (params?.artifactType) query.set('artifact_type', params.artifactType);
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return request(`/artifacts${suffix}`);
    },
    get(artifactId: string): Promise<ArtifactRef> {
      return request(`/artifacts/${artifactId}`);
    },
    comment(artifactId: string, payload: ArtifactCommentRequest): Promise<ArtifactRef> {
      return request(`/artifacts/${artifactId}/comment`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
  },

  approvals: {
    list(params?: { taskId?: string; sessionId?: string }): Promise<ApprovalRequest[]> {
      const query = new URLSearchParams();
      if (params?.taskId) query.set('task_id', params.taskId);
      if (params?.sessionId) query.set('session_id', params.sessionId);
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return request(`/approvals${suffix}`);
    },
    respond(approvalId: string, payload: ApprovalResponseRequest): Promise<ApprovalRequest> {
      return request(`/approvals/${approvalId}/respond`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
  },

  permissions: {
    listGrants(params?: { projectId?: string; taskId?: string }): Promise<PermissionGrant[]> {
      const query = new URLSearchParams();
      if (params?.projectId) query.set('project_id', params.projectId);
      if (params?.taskId) query.set('task_id', params.taskId);
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return request(`/permissions/grants${suffix}`);
    },
    createGrant(payload: PermissionGrantRequest): Promise<PermissionGrant> {
      return request('/permissions/grants', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    async revokeGrant(grantId: string): Promise<boolean> {
      const response = await request<{ revoked: boolean }>(`/permissions/grants/${grantId}`, {
        method: 'DELETE',
      });
      return response.revoked;
    },
  },

  events: {
    list(params?: { sessionId?: string; taskId?: string }): Promise<BuilderEvent[]> {
      const query = new URLSearchParams();
      if (params?.sessionId) query.set('session_id', params.sessionId);
      if (params?.taskId) query.set('task_id', params.taskId);
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return request(`/events${suffix}`);
    },
    stream(params?: { sessionId?: string; taskId?: string; since?: number }): EventSource {
      const query = new URLSearchParams();
      if (params?.sessionId) query.set('session_id', params.sessionId);
      if (params?.taskId) query.set('task_id', params.taskId);
      if (params?.since !== undefined) query.set('since', String(params.since));
      const suffix = query.toString() ? `?${query.toString()}` : '';
      return new EventSource(`/api/builder/events/stream${suffix}`);
    },
  },

  metrics: {
    get(projectId?: string): Promise<BuilderMetricsSnapshot> {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
      return request(`/metrics${suffix}`);
    },
  },

  specialists: {
    list(): Promise<SpecialistDefinition[]> {
      return request('/specialists');
    },
    invoke(role: SpecialistDefinition['role'], payload: SpecialistInvokeRequest): Promise<Record<string, unknown>> {
      return request(`/specialists/${role}/invoke`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
  },
};
