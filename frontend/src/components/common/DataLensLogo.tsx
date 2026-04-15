interface DataLensLogoProps {
  height?: number;
  color?: string;
  className?: string;
}

export default function DataLensLogo({ height = 24, color = '#6366f1', className }: DataLensLogoProps) {
  const w = height * 3.2;
  return (
    <svg
      viewBox="0 0 160 48"
      xmlns="http://www.w3.org/2000/svg"
      height={height}
      width={w}
      className={className}
      aria-label="DataLens"
      style={{ display: 'block' }}
    >
      {/* Lens icon */}
      <circle cx="18" cy="24" r="13" stroke={color} strokeWidth="2.5" fill="none" />
      <path d="M10 28 L15 20 L20 24 L26 16" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="15" cy="20" r="1.5" fill="#f97316" />
      <circle cx="26" cy="16" r="1.5" fill="#f97316" />

      {/* Text */}
      <text x="38" y="32" fontFamily="Inter, system-ui, sans-serif" fontWeight="700" fontSize="24" fill={color} letterSpacing="-0.5">
        Data<tspan fill="#f97316">Lens</tspan>
      </text>
    </svg>
  );
}
