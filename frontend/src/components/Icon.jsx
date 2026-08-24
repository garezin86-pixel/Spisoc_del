export function Icon({ d, size = 14 }) {
    return (
        <svg
            viewBox="0 0 24 24"
            style={{
                width: size,
                height: size,
                minWidth: size,
                minHeight: size,
                flexShrink: 0,
                display: "inline-block",
                verticalAlign: "middle",
                fill: "currentColor",
            }}
        >
            <path d={d} />
        </svg>
    );
}
