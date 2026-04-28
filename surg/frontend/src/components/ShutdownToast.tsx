import { useEffect, useState } from 'react';

interface Props {
  secondsRemaining: number | null;
  onKeepAlive: () => void;
}

export default function ShutdownToast({ secondsRemaining, onKeepAlive }: Props) {
  const [count, setCount] = useState(secondsRemaining ?? 0);

  useEffect(() => {
    if (secondsRemaining === null) return;
    setCount(secondsRemaining);
    const id = setInterval(() => setCount(c => Math.max(0, c - 1)), 1000);
    return () => clearInterval(id);
  }, [secondsRemaining]);

  if (secondsRemaining === null) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg bg-(--c-panel) border border-[#eab308] shadow-xl">
      <span className="text-[#eab308] text-sm">
        Idle shutdown in <strong>{count}s</strong>
      </span>
      <button
        onClick={onKeepAlive}
        className="px-3 py-1 text-xs rounded bg-[#eab308] text-black font-medium hover:bg-yellow-400 transition-colors"
      >
        Keep Alive
      </button>
    </div>
  );
}
