import { CircleAlert } from "lucide-react";

export function splitTickers(value: string) {
  return value
    .split(/[\s,]+/)
    .map((ticker) => ticker.trim().toUpperCase())
    .filter(Boolean);
}

export function dateLabel(value: string | null) {
  return value ? value.slice(0, 10) : "n/a";
}

export function readable(value: string) {
  return value.replaceAll("_", " ");
}

export function ToolError({ message }: { message: string }) {
  return (
    <div className="notice error tool-notice" role="alert">
      <CircleAlert size={18} aria-hidden="true" />
      <div>
        <strong>Research request failed</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}
