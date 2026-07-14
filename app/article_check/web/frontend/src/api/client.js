const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || res.statusText);
  }
  return res.json();
}

export const api = {
  // System
  status: () => request('/status'),
  upload: (file) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`${BASE}/upload`, { method: 'POST', body: form }).then(r => r.json());
  },

  // Review
  review: (paperPath, template, withDeep, reviewTrack = 'auto') => request('/review', {
    method: 'POST', body: JSON.stringify({ paper_path: paperPath, template, with_deep_review: withDeep, review_track: reviewTrack, depth: withDeep ? 'deep' : 'auto' }),
  }),
  deepReview: (paperPath, template, reviewTrack = 'auto') => request('/review/deep', {
    method: 'POST', body: JSON.stringify({ paper_path: paperPath, template, with_deep_review: true, review_track: reviewTrack, depth: 'deep' }),
  }),
  reportDialogue: (reportPayload, question) => request('/report/dialogue', {
    method: 'POST', body: JSON.stringify({ report_payload: reportPayload, question }),
  }),
  reportSourceSnippet: (reportPayload, evidenceId, contextRadius = 3) => request('/report/source-snippet', {
    method: 'POST',
    body: JSON.stringify({ report_payload: reportPayload, evidence_id: evidenceId, context_radius: contextRadius }),
  }),
  reportFileUrl: (path) => `${BASE}/report/file?path=${encodeURIComponent(path)}`,

  // Stream
  batchStream: (paths, options = {}) => {
    return fetch(`${BASE}/review/batch-stream`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths, ...options }),
    });
  },
};
