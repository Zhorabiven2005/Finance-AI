/**
 * Иконки категорий.
 *
 * Категории на backend по-прежнему хранят эмодзи в поле `icon` (см.
 * app/db/seed.py) — эта бизнес-логика не меняется. На фронтенде эмодзи
 * больше нигде не рендерится: вместо него по названию категории подбирается
 * иконка Lucide из единого набора. Для пользовательских категорий, которых
 * нет в таблице, используется нейтральная иконка по типу (доход/расход).
 */

import {
  Baby,
  Banknote,
  Bike,
  BookOpen,
  Briefcase,
  Bus,
  Car,
  Coffee,
  CreditCard,
  Dumbbell,
  Film,
  Fuel,
  Gamepad2,
  Gift,
  GraduationCap,
  Heart,
  HeartPulse,
  House,
  Landmark,
  type LucideIcon,
  MoreHorizontal,
  Music,
  PartyPopper,
  PawPrint,
  Percent,
  Pill,
  PiggyBank,
  Plane,
  Receipt,
  Repeat,
  Rotate3D,
  Scissors,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  Sofa,
  Sparkles,
  ShieldCheck,
  Ticket,
  TrainFront,
  Trophy,
  Undo2,
  Utensils,
  Wallet,
  Wifi,
  Wrench,
  Zap,
} from "lucide-react";

/** Набор иконок, из которых пользователь выбирает иконку категории. В БД
 * хранится ключ (kebab-case) — backend валидирует только его формат. */
export const CATEGORY_ICON_REGISTRY: Record<string, LucideIcon> = {
  "shopping-cart": ShoppingCart,
  "shopping-bag": ShoppingBag,
  utensils: Utensils,
  coffee: Coffee,
  house: House,
  sofa: Sofa,
  car: Car,
  fuel: Fuel,
  bus: Bus,
  "train-front": TrainFront,
  bike: Bike,
  plane: Plane,
  dumbbell: Dumbbell,
  "gamepad-2": Gamepad2,
  film: Film,
  music: Music,
  ticket: Ticket,
  "party-popper": PartyPopper,
  smartphone: Smartphone,
  wifi: Wifi,
  zap: Zap,
  wrench: Wrench,
  heart: Heart,
  "heart-pulse": HeartPulse,
  pill: Pill,
  scissors: Scissors,
  sparkles: Sparkles,
  shirt: Shirt,
  baby: Baby,
  "paw-print": PawPrint,
  "book-open": BookOpen,
  "graduation-cap": GraduationCap,
  briefcase: Briefcase,
  wallet: Wallet,
  banknote: Banknote,
  "credit-card": CreditCard,
  "piggy-bank": PiggyBank,
  landmark: Landmark,
  receipt: Receipt,
  gift: Gift,
  trophy: Trophy,
};

export const CATEGORY_ICON_KEYS = Object.keys(CATEGORY_ICON_REGISTRY);

const NAME_TO_ICON: Record<string, LucideIcon> = {
  // Доходы
  "Зарплата": Wallet,
  "Премия": Trophy,
  "Подработка / фриланс": Banknote,
  "Инвестиции": Landmark,
  "Дивиденды": PiggyBank,
  "Проценты по вкладам": Percent,
  "Подарки": Gift,
  "Возврат долга": Undo2,
  "Продажа имущества": Rotate3D,

  // Расходы
  "Продукты": ShoppingCart,
  "Кафе и рестораны": Utensils,
  "Транспорт": Bus,
  "Автомобиль": Car,
  "Жильё": House,
  "Коммунальные услуги": Zap,
  "Связь и интернет": Smartphone,
  "Здоровье и аптека": HeartPulse,
  "Одежда и обувь": Shirt,
  "Развлечения": Ticket,
  "Спорт и фитнес": Dumbbell,
  "Образование": GraduationCap,
  "Подписки и сервисы": Repeat,
  "Путешествия": Plane,
  "Дом и быт": Sofa,
  "Красота и уход": Sparkles,
  "Подарки и праздники": PartyPopper,
  "Питомцы": PawPrint,
  "Дети": Baby,
  "Страхование": ShieldCheck,
  "Налоги и взносы": Receipt,
  "Погашение долга": CreditCard,
};

const FALLBACK_ICON: Record<"income" | "expense", LucideIcon> = {
  income: Wallet,
  expense: MoreHorizontal,
};

/** Приоритет: выбранная пользователем иконка (ключ из реестра) → иконка по
 * названию базовой категории → нейтральная по типу. Старые эмодзи из seed
 * в реестре не найдутся и тихо уступают место подбору по названию. */
export function iconForCategory(
  name: string,
  type: "income" | "expense",
  icon?: string | null,
): LucideIcon {
  if (icon) {
    const chosen = CATEGORY_ICON_REGISTRY[icon];
    if (chosen) return chosen;
  }
  return NAME_TO_ICON[name] ?? FALLBACK_ICON[type];
}

export function CategoryIcon({
  name,
  type,
  icon,
  className = "h-4 w-4",
}: {
  name: string;
  type: "income" | "expense";
  icon?: string | null | undefined;
  className?: string;
}) {
  const Icon = iconForCategory(name, type, icon);
  return <Icon className={className} strokeWidth={1.75} aria-hidden />;
}
