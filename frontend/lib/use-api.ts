"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T) => void;
}

/** GET a path; re-fetches when the path changes. Pass null to skip. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const latest = useRef(path);
  latest.current = path;

  const load = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (latest.current === path) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (latest.current === path) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      if (latest.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
