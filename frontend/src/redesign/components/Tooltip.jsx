import * as RT from "@radix-ui/react-tooltip";

export function Tooltip({ content, children, side = "top", delay = 200 }) {
  if (!content) return children;
  return (
    <RT.Provider delayDuration={delay}>
      <RT.Root>
        <RT.Trigger asChild>{children}</RT.Trigger>
        <RT.Portal>
          <RT.Content
            side={side}
            sideOffset={6}
            className="z-50 max-w-xs rounded-lg border border-line-2 bg-surface px-2.5 py-1.5 text-xs text-text-secondary shadow-e3
                       data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0"
          >
            {content}
            <RT.Arrow className="fill-surface" />
          </RT.Content>
        </RT.Portal>
      </RT.Root>
    </RT.Provider>
  );
}

export default Tooltip;
