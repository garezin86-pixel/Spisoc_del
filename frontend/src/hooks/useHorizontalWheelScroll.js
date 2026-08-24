import { useEffect, useRef } from "react";

export function useHorizontalWheelScroll() {
    const ref = useRef(null);
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        function onWheel(e) {
            if (e.deltaY === 0) return;
            el.scrollLeft += e.deltaY;
            e.preventDefault();
        }
        el.addEventListener("wheel", onWheel, { passive: false });
        return () => el.removeEventListener("wheel", onWheel);
    }, []);
    return ref;
}

// ─── Icons ────────────────────────────────────────────────
