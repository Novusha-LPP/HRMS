import { closestCenter, pointerWithin } from "@dnd-kit/core";
import type { CollisionDetection, KeyboardCoordinateGetter } from "@dnd-kit/core";

// A large card's centre can be over a different widget from the pointer. Keep the
// grid stationary and target the card actually under the pointer, including its grip.
// Outside a card there is no drop target. Keyboard drags have no pointer coordinates.
export const dashboardCollisionDetection: CollisionDetection = (args) =>
  args.pointerCoordinates ? pointerWithin(args) : closestCenter(args);

// Align the dragged card's centre with its keyboard target. Edge alignment (the
// sortable default) can select a neighbouring card when the two widths differ.
export const dashboardKeyboardCoordinates: KeyboardCoordinateGetter = (event, {
  currentCoordinates,
  context: { active, over, collisionRect, droppableRects, droppableContainers },
}) => {
  if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code)) return;
  event.preventDefault();
  if (!active || !collisionRect) return;

  const currentId = over?.id ?? active.id;
  const origin = droppableRects.get(currentId);
  if (!origin) return;
  const originX = origin.left + origin.width / 2;
  const originY = origin.top + origin.height / 2;
  let target: { x: number; y: number } | undefined;
  let nearest = Infinity;
  let targetAligned = false;
  const horizontal = event.code === "ArrowLeft" || event.code === "ArrowRight";

  for (const container of droppableContainers.getEnabled()) {
    if (container.id === currentId) continue;
    const rect = droppableRects.get(container.id);
    if (!rect) continue;
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const dx = x - originX;
    const dy = y - originY;
    const inDirection = event.code === "ArrowRight" ? dx > 1
      : event.code === "ArrowLeft" ? dx < -1
      : event.code === "ArrowDown" ? dy > 1 : dy < -1;
    // Prefer a neighbour in this row/column over a closer diagonal card.
    const aligned = horizontal
      ? rect.top < origin.bottom && rect.bottom > origin.top
      : rect.left < origin.right && rect.right > origin.left;
    const distance = dx * dx + dy * dy;
    if (inDirection && ((!targetAligned && aligned) || (aligned === targetAligned && distance < nearest))) {
      nearest = distance;
      target = { x, y };
      targetAligned = aligned;
    }
  }

  if (target) {
    return {
      x: currentCoordinates.x + target.x - (collisionRect.left + collisionRect.width / 2),
      y: currentCoordinates.y + target.y - (collisionRect.top + collisionRect.height / 2),
    };
  }
};
