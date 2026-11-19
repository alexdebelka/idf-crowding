import { RabbitMark } from "@/components/shared/Header";
import { People } from "@/components/shared/People";
import type { CrowdLayer, Rabbit } from "./logic";
import styles from "./station.module.css";

/** A band of people (decorative, `aria-hidden`): the headline carries the state in words. */
export function CrowdBand({
  layer,
  tone,
  id,
  rabbit,
  className,
}: {
  layer: CrowdLayer;
  tone: "night" | "calm";
  id: string;
  rabbit?: Rabbit | null;
  className?: string;
}) {
  const top = layer.anchor === "top";
  return (
    <div
      aria-hidden="true"
      className={`${styles.band} ${top ? styles.bandTop : styles.bandBottom}${className ? ` ${className}` : ""}`}
      style={top ? { height: layer.height } : { minHeight: layer.minVisible }}
    >
      <People
        rows={layer.rows}
        width={layer.width}
        height={layer.height}
        tone={tone}
        id={id}
        className={`${styles.people} ${top ? styles.peopleTop : styles.peopleBottom}`}
      />
      {rabbit ? <RabbitFigure rabbit={rabbit} /> : null}
    </div>
  );
}

/** The rabbit stands in the front layer, bottom right, with a soft shadow (spec, section 6). */
function RabbitFigure({ rabbit }: { rabbit: Rabbit }) {
  const w = (rabbit.height * 100) / 134;
  return (
    <>
      <span
        className={styles.rabbitShadow}
        style={{
          right: rabbit.right - w * 0.1,
          bottom: rabbit.bottom - rabbit.height * 0.06,
          width: w * 1.2,
          height: Math.max(12, rabbit.height * 0.15),
        }}
      />
      <span className={styles.rabbitFigure} style={{ right: rabbit.right, bottom: rabbit.bottom }}>
        <RabbitMark height={rabbit.height} />
      </span>
    </>
  );
}

/** Computer, calm: people behind the bars, drawn under the chart (never over it). */
export function BackLayer({ layer, id }: { layer: CrowdLayer; id: string }) {
  return (
    <div aria-hidden="true" className={styles.backLayer} style={{ height: layer.height }}>
      <People rows={layer.rows} width={layer.width} height={layer.height} tone="calm" id={id} className={styles.people} />
    </div>
  );
}
