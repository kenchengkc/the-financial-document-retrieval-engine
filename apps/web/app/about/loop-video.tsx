"use client";

import { useEffect, useRef } from "react";

// React omits the `muted` attribute during SSR, which blocks autoplay in
// Chrome/Safari — so mute via ref and kick off playback explicitly.
export function LoopVideo({ src, poster }: { src: string; poster: string }) {
  const ref = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    video.muted = true;
    video.play().catch(() => {});
  }, []);

  return (
    <video
      ref={ref}
      className="ih-video"
      src={src}
      poster={poster}
      autoPlay
      muted
      loop
      playsInline
    />
  );
}
