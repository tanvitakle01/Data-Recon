import React from "react";

function SkeletonLine({ w = "100%" }) {
  return <div className="h-3 rounded bg-slate-200 animate-pulse" style={{ width: w }} />;
}

export function SkeletonCard({ className = "" }) {
  return (
    <div className={`rounded-2xl border border-slate-200 bg-white/70 p-4 ${className}`}>
      <SkeletonLine w="60%" />
      <div className="mt-3 space-y-2">
        <SkeletonLine w="90%" />
        <SkeletonLine w="70%" />
        <SkeletonLine w="80%" />
      </div>
    </div>
  );
}

export default function SkeletonCards() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SkeletonCard />
      <SkeletonCard />
    </div>
  );
}

