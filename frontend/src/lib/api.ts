/** Typed client for the HerMediSafe API. Shapes mirror backend/API_CONTRACT.md. */

export type ContextType = "general" | "planning_pregnancy" | "pregnant" | "breastfeeding";
export type Severity = "high" | "moderate" | "low" | "none";
export type MedicineStatus = "active" | "discontinued" | "rejected";
export type SourceType = "prescription" | "otc" | "self_reported";

export interface UserProfile {
  id: number;
  context_type: ContextType;
  trimester: number | null;
  infant_age_months: number | null;
  is_premature_infant: boolean | null;
}

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  created_at: string;
  consent_given_at: string | null;
  profile: UserProfile | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: number;
  email: string;
}

export interface JanAushadhiOption {
  product_name: string;
  unit: string;
  mrp_inr: number;
}

export interface Medicine {
  id: number;
  prescription_id: number | null;
  source: SourceType;
  raw_name: string;
  normalized_ingredient: string | null;
  brand_name: string | null;
  strength: string | null;
  dose: string | null;
  frequency: string | null;
  duration: string | null;
  confidence_score: number | null;
  is_confirmed: boolean;
  status: MedicineStatus;
  created_at: string;
  jan_aushadhi: JanAushadhiOption | null;
}

export interface Prescription {
  id: number;
  file_url: string;
  file_type: "image" | "pdf";
  uploaded_at: string;
  source_type: SourceType;
  medicine_count: number;
  pending_review_count: number;
}

export interface PrescriptionDetail extends Prescription {
  medicines: Pick<
    Medicine,
    | "id"
    | "raw_name"
    | "normalized_ingredient"
    | "strength"
    | "dose"
    | "frequency"
    | "duration"
    | "confidence_score"
    | "is_confirmed"
    | "status"
  >[];
}

export interface EvidenceReference {
  id: number;
  alert_id: number;
  title: string;
  url: string;
  retrieved_at: string;
}

export interface InteractionAlert {
  id: number;
  user_id: number;
  severity: Severity;
  rationale: string;
  source_reference: string | null;
  reviewed_by_professional: boolean;
  created_at: string;
  medicine_names: string[];
  evidence_references: EvidenceReference[];
}

export interface DuplicateFlag {
  id: number;
  medicine_a: Medicine;
  medicine_b: Medicine;
  detected_at: string;
  resolved: boolean;
  resolved_at: string | null;
  resolution: string | null;
}

export interface Reminder {
  id: number;
  user_id: number;
  medicine_id: number;
  medicine_name: string;
  time_of_day: string;
  frequency: string;
  is_active: boolean;
  created_at: string;
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  resource_type: string;
  resource_id: string;
  timestamp: string;
  ip_address: string | null;
}

export type AssistantLanguage = "en" | "hi";

export interface AssistantAnswer {
  answer: string;
  model_used: string;
  disclaimer: string;
  language: AssistantLanguage;
}

export interface MedicationSummary {
  generated_at: string;
  user_id: number;
  confirmed_medicines: {
    id: number;
    raw_name: string;
    brand_name: string | null;
    normalized_ingredient: string | null;
    strength: string | null;
    dose: string | null;
    frequency: string | null;
    duration: string | null;
    source: SourceType;
    confidence_score: number | null;
    created_at: string;
  }[];
  pending_review: { id: number; raw_name: string; confidence_score: number | null }[];
  unresolved_duplicates: { flag_id: number; medicine_a: string; medicine_b: string }[];
  active_alerts: {
    id: number;
    severity: Severity;
    rationale: string;
    reviewed_by_professional: boolean;
    medicines: string[];
  }[];
  summary_counts: {
    confirmed_active: number;
    pending_review: number;
    unresolved_duplicates: number;
    active_alerts: number;
    high_severity_alerts: number;
  };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const TOKEN_KEY = "hermedisafe.token";

export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010").replace(
  /\/$/,
  "",
);

export const tokenStore = {
  read: () => localStorage.getItem(TOKEN_KEY),
  write: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Turn FastAPI's `detail` (a string, or a 422 validation array) into one sentence. */
function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { loc?: unknown[]; msg?: string };
    const field = first?.loc?.slice(-1)[0] ?? "request";
    return `${String(field)}: ${first?.msg ?? "invalid"}`;
  }
  return "Request failed";
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  /** Return the raw response instead of parsed JSON (binary downloads). */
  raw?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = tokenStore.read();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: options.method ?? (options.body || options.form ? "POST" : "GET"),
    headers,
    body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  });

  if (!response.ok) {
    if (response.status === 401) tokenStore.clear();
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      message = detailMessage(payload.detail);
    } catch {
      /* a non-JSON error body leaves the status text in place */
    }
    throw new ApiError(response.status, message);
  }

  if (options.raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () =>
    request<{ status: string; database: string; service: string; version: string }>("/health"),

  signup: (input: { email: string; password: string; full_name: string }) =>
    request<TokenResponse>("/auth/signup", { body: input }),
  login: (input: { email: string; password: string }) =>
    request<TokenResponse>("/auth/login", { body: input }),
  googleLogin: (idToken: string) =>
    request<TokenResponse>("/auth/google", { body: { credential: idToken } }),

  me: () => request<CurrentUser>("/users/me"),
  saveProfile: (input: {
    context_type: ContextType;
    trimester?: number | null;
    infant_age_months?: number | null;
    is_premature_infant?: boolean | null;
  }) => request<UserProfile>("/users/me/profile", { body: input }),
  giveConsent: () =>
    request<{ consent_given_at: string; already_recorded: boolean }>("/users/me/consent", {
      body: {},
    }),

  prescriptions: () => request<{ items: Prescription[]; total: number }>("/prescriptions"),
  prescription: (id: number) => request<PrescriptionDetail>(`/prescriptions/${id}`),
  uploadPrescription: (file: File, sourceType: SourceType = "prescription") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return request<Prescription>("/prescriptions/upload", { form });
  },
  deletePrescription: (id: number) =>
    request<void>(`/prescriptions/${id}`, { method: "DELETE" }),
  runMockOcr: (id: number) => request<PrescriptionDetail>(`/prescriptions/${id}/mock-ocr`, { body: {} }),
  ingestOcr: (id: number, medicines: unknown[]) =>
    request<Medicine[]>(`/prescriptions/${id}/ocr-results`, { body: { medicines } }),

  medicines: (params: { confirmed?: boolean; status?: MedicineStatus } = {}) => {
    const query = new URLSearchParams();
    if (params.confirmed !== undefined) query.set("confirmed", String(params.confirmed));
    if (params.status) query.set("status", params.status);
    const suffix = query.size ? `?${query}` : "";
    return request<Medicine[]>(`/medicines${suffix}`);
  },
  pendingReview: () => request<Medicine[]>("/medicines/pending-review"),
  addMedicine: (input: {
    raw_name: string;
    brand_name?: string;
    strength?: string;
    dose?: string;
    frequency?: string;
    duration?: string;
  }) => request<Medicine>("/medicines", { body: input }),
  confirmMedicine: (id: number, input: Record<string, string | null> = {}) =>
    request<Medicine>(`/medicines/${id}/confirm`, { method: "PATCH", body: input }),
  rejectMedicine: (id: number, reason?: string) =>
    request<Medicine>(`/medicines/${id}/reject`, {
      method: "PATCH",
      body: reason ? { reason } : {},
    }),

  duplicates: (includeResolved = false) =>
    request<DuplicateFlag[]>(`/medicines/duplicates?include_resolved=${includeResolved}`),
  resolveDuplicate: (
    flagId: number,
    input: { resolution: "keep_both" | "merged" | "not_a_duplicate"; kept_medicine_id?: number },
  ) =>
    request<{ id: number; resolved: boolean; resolution: string }>(
      `/medicines/duplicates/${flagId}/resolve`,
      { method: "PATCH", body: input },
    ),

  checkInteractions: () =>
    request<{ new_alerts_created: number; total_active_alerts: number }>(
      "/medicines/check-interactions",
      { body: {} },
    ),
  alerts: () => request<InteractionAlert[]>("/alerts"),
  markReviewed: (id: number) =>
    request<InteractionAlert>(`/alerts/${id}/mark-reviewed`, { method: "PATCH", body: {} }),
  addEvidence: (
    id: number,
    input: { source_reference?: string; evidence_items: { title: string; url: string }[] },
  ) =>
    request<InteractionAlert>(`/alerts/${id}/evidence`, { method: "PATCH", body: input }),

  reminders: (params: { is_active?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.is_active !== undefined) query.set("is_active", String(params.is_active));
    const suffix = query.size ? `?${query}` : "";
    return request<Reminder[]>(`/reminders${suffix}`);
  },
  addReminder: (input: { medicine_id: number; time_of_day: string; frequency: string }) =>
    request<Reminder>("/reminders", { body: input }),
  updateReminder: (
    id: number,
    input: { time_of_day?: string; frequency?: string; is_active?: boolean },
  ) => request<Reminder>(`/reminders/${id}`, { method: "PATCH", body: input }),
  deleteReminder: (id: number) =>
    request<{ deleted_at: string }>(`/reminders/${id}`, { method: "DELETE" }),

  summary: () => request<MedicationSummary>("/reports/medication-summary"),
  summaryPdf: () => request<Response>("/reports/medication-summary/pdf", { raw: true }),

  auditLogs: (limit = 20) =>
    request<{ items: AuditLog[]; total: number }>(`/audit-logs?limit=${limit}`),

  askAssistant: (question: string, language: AssistantLanguage = "en") =>
    request<AssistantAnswer>("/assistant/ask", { body: { question, language } }),
};
