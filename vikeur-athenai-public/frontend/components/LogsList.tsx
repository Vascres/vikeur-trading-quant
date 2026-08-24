import type { LogEntry } from "@/lib/api";

export default function LogsList({ logs }: { logs: LogEntry[] }) {
  if (logs.length === 0) {
    return <p className="text-neutral-400 text-sm">Aucun événement récent.</p>;
  }

  return (
    <ul className="space-y-1 text-xs font-mono max-h-96 overflow-y-auto">
      {logs.map((log) => (
        <li key={log.id} className="border-b border-border/50 py-1.5">
          <span className="text-neutral-500">{new Date(log.time).toLocaleTimeString("fr-FR")}</span>{" "}
          <span className="text-blue-400">[{log.source_module}]</span>{" "}
          <span className="text-neutral-200">{log.event_type}</span>
        </li>
      ))}
    </ul>
  );
}
