import * as React from "react";
import { cn } from "../../lib/utils";

const SIZES = {
  sm: "h-7 w-7 text-xs",
  md: "h-9 w-9 text-sm",
  lg: "h-12 w-12 text-base",
} as const;

export interface AvatarProps extends React.HTMLAttributes<HTMLDivElement> {
  src?: string;
  /** Name used for the initials fallback and image alt text. */
  name?: string;
  size?: keyof typeof SIZES;
  alt?: string;
}

function initials(name?: string): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Circular user avatar — shows the image, or initials when absent/broken. */
export const Avatar: React.FC<AvatarProps> = ({
  src,
  name,
  size = "md",
  alt,
  className,
  ...props
}) => {
  const [errored, setErrored] = React.useState(false);
  const showImage = Boolean(src) && !errored;

  return (
    <div
      className={cn(
        "inline-flex flex-shrink-0 select-none items-center justify-center overflow-hidden rounded-full bg-[var(--bcone-teal)]/15 font-bold text-[var(--bcone-teal)]",
        SIZES[size],
        className
      )}
      {...props}
    >
      {showImage ? (
        <img
          src={src}
          alt={alt ?? name ?? ""}
          className="h-full w-full object-cover"
          onError={() => setErrored(true)}
        />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
    </div>
  );
};
Avatar.displayName = "Avatar";
