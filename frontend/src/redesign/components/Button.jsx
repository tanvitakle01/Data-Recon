import { cva } from "class-variance-authority";
import { cn } from "../lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium " +
    "transition-[background-color,color,box-shadow,border-color] duration-150 ease-[cubic-bezier(0.2,0,0,1)] " +
    "select-none disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-2 focus-visible:outline-accent",
  {
    variants: {
      variant: {
        primary: "bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-active shadow-e1",
        secondary: "bg-surface text-text border border-line-2 hover:bg-surface-2 hover:border-line-3",
        ghost: "bg-transparent text-text-secondary hover:bg-surface-2 hover:text-text",
        destructive: "bg-missing-solid text-white hover:brightness-95 active:brightness-90 shadow-e1",
      },
      size: {
        sm: "h-7 px-2.5 text-[13px] leading-5",
        md: "h-[34px] px-3.5 text-sm",
        lg: "h-10 px-[18px] text-sm",
      },
      iconOnly: { true: "px-0 aspect-square", false: "" },
    },
    defaultVariants: { variant: "primary", size: "md", iconOnly: false },
  }
);

export function Button({ variant, size, iconOnly, className, children, ...props }) {
  return (
    <button className={cn(button({ variant, size, iconOnly }), className)} {...props}>
      {children}
    </button>
  );
}

export default Button;
