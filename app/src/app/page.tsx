import { HomeScreen } from "@/components/home/HomeScreen";
import { getIndex } from "@/lib/data";
import { bandRules } from "@/lib/state";

export default function Home() {
  const index = getIndex();
  return <HomeScreen places={index.places} bands={bandRules(index)} />;
}
