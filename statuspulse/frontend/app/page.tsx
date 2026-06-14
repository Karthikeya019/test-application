"use client";

import { useState, useEffect } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type Service = {
  id: string;
  name: string;
  status: "operational" | "degraded" | "down";
  last_updated: string;
  detail: string | null;
};

type UptimeData = {
  uptime_percent: number;
};

type HistoryData = {
  avg_response_ms: number | null;
  latest_response_ms: number | null;
  checks: { status: "operational" | "degraded" | "down" }[];
};

type CacheStats = {
  hits: number;
  misses: number;
  hit_rate_percent: number;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function timeAgo(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "unknown";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

// segment and dot colors — 500/600 weight for accessible contrast on white
const segmentBg: Record<Service["status"], string> = {
  operational: "bg-green-500",
  degraded:    "bg-yellow-500",
  down:        "bg-red-500",
};

const dotBg: Record<Service["status"], string> = {
  operational: "bg-green-500",
  degraded:    "bg-yellow-500",
  down:        "bg-red-500",
};

// status label colors — darker shade for text legibility on white cards
const statusText: Record<Service["status"], string> = {
  operational: "text-green-600",
  degraded:    "text-yellow-600",
  down:        "text-red-600",
};

// ---------------------------------------------------------------------------
// HistoryBar — compact colored strip, oldest left → newest right
// ---------------------------------------------------------------------------
function HistoryBar({ checks }: { checks: HistoryData["checks"] }) {
  const ordered = [...checks].reverse();

  return (
    <div>
      <div className="flex h-3.5 gap-px overflow-hidden rounded-full bg-gray-100">
        {ordered.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-xs text-gray-400">
            no data yet
          </div>
        ) : (
          ordered.map((c, i) => (
            <div key={i} className={`flex-1 ${segmentBg[c.status]}`} />
          ))
        )}
      </div>
      {ordered.length > 0 && (
        <div className="mt-0.5 flex justify-between text-xs text-gray-400">
          <span>older</span>
          <span>now</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ServiceCard
// ---------------------------------------------------------------------------
function ServiceCard({
  service,
  uptime,
  history,
}: {
  service: Service;
  uptime: UptimeData | null;
  history: HistoryData | null;
}) {
  const avg    = history?.avg_response_ms    ?? null;
  const latest = history?.latest_response_ms ?? null;

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      {/* header: dot + name + status word */}
      <div className="mb-1.5 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dotBg[service.status]}`} />
        <span className="text-base font-semibold text-gray-900">{service.name}</span>
        <span className={`ml-auto text-sm font-medium capitalize ${statusText[service.status]}`}>
          {service.status}
        </span>
      </div>

      {/* detail — reason from the health-checker (e.g. "HTTP 200, 182ms") */}
      {service.detail && (
        <p className="mb-2 text-sm text-gray-500">{service.detail}</p>
      )}

      {/* metrics row */}
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500">
        <span>
          24h uptime{" "}
          <span className="font-medium text-gray-800">
            {uptime != null ? `${uptime.uptime_percent}%` : "—"}
          </span>
        </span>
        <span>
          latest{" "}
          <span className="font-medium text-gray-800">
            {latest != null ? `${latest}ms` : "—"}
          </span>
        </span>
        <span>
          avg (60){" "}
          <span className="font-medium text-gray-800">
            {avg != null ? `${avg}ms` : "—"}
          </span>
        </span>
        <span className="ml-auto text-gray-400">
          updated {timeAgo(service.last_updated)}
        </span>
      </div>

      {/* history strip */}
      {history && <HistoryBar checks={history.checks} />}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function Home() {
  const [services,   setServices]   = useState<Service[]>([]);
  const [uptimes,    setUptimes]    = useState<Record<string, UptimeData>>({});
  const [histories,  setHistories]  = useState<Record<string, HistoryData>>({});
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);

  useEffect(() => {
    async function fetchAll() {
      try {
        const res = await fetch(`${API}/services`);
        if (!res.ok) throw new Error(`Services endpoint returned ${res.status}`);
        const svcs: Service[] = await res.json();
        setServices(svcs);
        setError(null);

        // fetch per-service uptime + history and cache stats all in parallel
        const [uptimeResults, historyResults, statsRes] = await Promise.all([
          Promise.all(
            svcs.map((s) =>
              fetch(`${API}/services/${s.id}/uptime?hours=24`)
                .then((r) => (r.ok ? r.json() : null))
                .catch(() => null)
            )
          ),
          Promise.all(
            svcs.map((s) =>
              fetch(`${API}/services/${s.id}/history?limit=60`)
                .then((r) => (r.ok ? r.json() : null))
                .catch(() => null)
            )
          ),
          fetch(`${API}/cache/stats`)
            .then((r) => (r.ok ? r.json() : null))
            .catch(() => null),
        ]);

        const newUptimes: Record<string, UptimeData>    = {};
        const newHistories: Record<string, HistoryData> = {};
        svcs.forEach((s, i) => {
          if (uptimeResults[i])  newUptimes[s.id]    = uptimeResults[i];
          if (historyResults[i]) newHistories[s.id]  = historyResults[i];
        });

        setUptimes(newUptimes);
        setHistories(newHistories);
        if (statsRes) setCacheStats(statsRes);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch");
      } finally {
        setLoading(false);
      }
    }

    fetchAll();
    const interval = setInterval(fetchAll, 10_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return (
    <div className="min-h-screen bg-gray-50 p-8 text-gray-500">Loading…</div>
  );
  if (error) return (
    <div className="min-h-screen bg-gray-50 p-8 text-red-600">{error}</div>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="mx-auto max-w-4xl px-4 py-10">
        {/* page header */}
        <div className="mb-7">
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">StatusPulse</h1>
          {cacheStats && (
            <p className="mt-1.5 text-sm text-gray-500">
              Cache hit rate{" "}
              <span className="font-medium text-gray-700">{cacheStats.hit_rate_percent}%</span>
              {" "}({cacheStats.hits} hits / {cacheStats.misses} misses)
              <span className="ml-1 text-xs text-gray-400">
                — low hit-rate is expected: short TTL + frequent invalidation
              </span>
            </p>
          )}
        </div>

        {/* service cards */}
        <ul className="space-y-3">
          {services.map((service) => (
            <ServiceCard
              key={service.id}
              service={service}
              uptime={uptimes[service.id]   ?? null}
              history={histories[service.id] ?? null}
            />
          ))}
        </ul>
      </main>
    </div>
  );
}
