import type { Metadata } from "next";
import { StationScreen } from "@/components/station/StationScreen";
import { getIndex, getPlace } from "@/lib/data";
import { bandRules } from "@/lib/state";

export const dynamicParams = false;

export function generateStaticParams() {
  return getIndex().places.map((p) => ({ id: p.id }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const p = getPlace(id).place;
  return {
    title: p.name,
    description: `L’affluence prévue à ${p.name}${p.town ? ` (${p.town})` : ""}, heure par heure, aujourd’hui et pour une date choisie.`,
  };
}

export default async function PlacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StationScreen data={getPlace(id)} bands={bandRules(getIndex())} />;
}
