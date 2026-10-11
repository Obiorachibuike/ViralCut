'use client';

import { useEffect, useState } from 'react';

export interface JobStreamEvent {
  type: string;
  jobId: string;
  stage?: string;
  progress?: number;
  message?: string;
  payload?: unknown;
  at?: number;
}

/** Subscribes to a job's SSE stream and returns the latest events. */
export function useJobStream(jobId: string | null) {
  const [events, setEvents] = useState<JobStreamEvent[]>([]);
  const [latest, setLatest] = useState<JobStreamEvent | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const source = new EventSource(`/api/jobs/${jobId}/stream`);
    const onMessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as JobStreamEvent;
        setLatest(event);
        setEvents((prev) => [...prev.slice(-50), event]);
      } catch {
        /* ignore */
      }
    };
    source.onmessage = onMessage;
    return () => source.close();
  }, [jobId]);

  return { events, latest };
}
