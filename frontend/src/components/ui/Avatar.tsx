const TONES = [
  "bg-brand-500/15 text-accent",
  "bg-info/10 text-info",
  "bg-plum/10 text-plum",
  "bg-warning/10 text-warning",
  "bg-success/10 text-success",
  "bg-danger/10 text-danger",
];

const SIZES = {
  xs: "h-6 w-6 text-[10px]",
  sm: "h-7 w-7 text-[11px]",
  md: "h-8 w-8 text-xs",
  lg: "h-10 w-10 text-sm",
  xl: "h-14 w-14 text-lg",
};

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "?";
}

export function Avatar({ name, size = "md", className = "" }: {
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
  const tone = TONES[Math.abs(hash) % TONES.length];
  return (
    <span
      className={`inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold ${SIZES[size]} ${tone} ${className}`}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
