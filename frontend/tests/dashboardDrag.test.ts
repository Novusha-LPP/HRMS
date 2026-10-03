import assert from "node:assert/strict";
import { test } from "node:test";
import type {
  ClientRect, CollisionDetection, DroppableContainer, KeyboardCoordinateGetter,
} from "@dnd-kit/core";
import {
  dashboardCollisionDetection, dashboardKeyboardCoordinates,
} from "../src/components/dashboard/dashboardDrag.ts";

const rect = (left: number, top: number, width: number, height: number): ClientRect => ({
  left, top, width, height, right: left + width, bottom: top + height,
});

function container(id: string, bounds: ClientRect, disabled = false): DroppableContainer {
  return {
    id, key: id, disabled, data: { current: {} },
    node: { current: null }, rect: { current: bounds },
  };
}

function collisionArgs(pointerCoordinates: { x: number; y: number } | null): Parameters<CollisionDetection>[0] {
  const initial = rect(0, 0, 600, 100);
  const moved = rect(0, 120, 600, 100);
  const containers = [
    container("active", initial),
    container("small", rect(0, 120, 100, 100)),
    container("wide", rect(120, 120, 480, 100)),
  ];
  return {
    active: { id: "active", data: { current: {} }, rect: { current: { initial, translated: moved } } },
    collisionRect: moved,
    droppableRects: new Map(containers.map((item) => [item.id, item.rect.current!])),
    droppableContainers: containers,
    pointerCoordinates,
  };
}

test("pointer targets the small card beneath it even when a wide dragged card's center is elsewhere", () => {
  const collisions = dashboardCollisionDetection(collisionArgs({ x: 40, y: 170 }));
  assert.deepEqual(collisions.map((collision) => collision.id), ["small"]);
});

test("dropping outside the grid does not select a nearby widget", () => {
  assert.deepEqual(dashboardCollisionDetection(collisionArgs({ x: -20, y: 170 })), []);
});

test("keyboard drags without pointer coordinates use the nearest card center", () => {
  const collisions = dashboardCollisionDetection(collisionArgs(null));
  assert.equal(collisions[0]?.id, "wide");
});

function keyboardArgs({
  containers,
  collisionRect,
  coordinates,
  overId = null,
}: {
  containers: DroppableContainer[];
  collisionRect: ClientRect;
  coordinates: { x: number; y: number };
  overId?: string | null;
}): Parameters<KeyboardCoordinateGetter>[1] {
  const map = Object.assign(new Map(containers.map((item) => [item.id, item])), {
    getEnabled: () => containers.filter((item) => !item.disabled),
    toArray: () => containers,
  });
  const activeRect = containers.find((item) => item.id === "active")!.rect.current!;
  const over = containers.find((item) => item.id === overId);
  return {
    active: "active",
    currentCoordinates: coordinates,
    context: {
      active: {
        id: "active", data: { current: {} },
        rect: { current: { initial: activeRect, translated: collisionRect } },
      },
      collisionRect,
      droppableRects: new Map(containers.map((item) => [item.id, item.rect.current!])),
      droppableContainers: map,
      over: over ? { id: over.id, rect: over.rect.current!, disabled: over.disabled, data: over.data } : null,
    },
  } as Parameters<KeyboardCoordinateGetter>[1];
}

const key = (code: string) => ({ code, preventDefault() {} }) as KeyboardEvent;

test("keyboard moves from the current target after a wide widget reaches a narrow card", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 600, 100)),
      container("current", rect(0, 120, 100, 100)),
      container("next", rect(120, 120, 100, 100)),
    ],
    collisionRect: rect(-250, 120, 600, 100),
    coordinates: { x: -250, y: 120 },
    overId: "current",
  });
  assert.deepEqual(dashboardKeyboardCoordinates(key("ArrowRight"), args), { x: -130, y: 120 });
});

test("keyboard centers a wide widget over the closest card in the next row", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 600, 100)),
      container("far", rect(0, 120, 100, 100)),
      container("near", rect(120, 120, 300, 100)),
    ],
    collisionRect: rect(0, 0, 600, 100),
    coordinates: { x: 0, y: 0 },
  });
  assert.deepEqual(dashboardKeyboardCoordinates(key("ArrowDown"), args), { x: -30, y: 120 });
});

test("keyboard skips disabled cards when choosing a destination", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 100, 100)),
      container("disabled", rect(120, 0, 100, 100), true),
      container("available", rect(240, 0, 100, 100)),
    ],
    collisionRect: rect(0, 0, 100, 100),
    coordinates: { x: 0, y: 0 },
  });
  assert.deepEqual(dashboardKeyboardCoordinates(key("ArrowRight"), args), { x: 240, y: 0 });
});

test("keyboard right prefers a card in the same row over a nearer diagonal card", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 600, 100)),
      container("diagonal", rect(300, 120, 100, 100)),
      container("same-row", rect(620, 0, 100, 100)),
    ],
    collisionRect: rect(0, 0, 600, 100),
    coordinates: { x: 0, y: 0 },
  });
  assert.deepEqual(dashboardKeyboardCoordinates(key("ArrowRight"), args), { x: 370, y: 0 });
});

test("keyboard down prefers a card in the same column over a nearer diagonal card", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 100, 600)),
      container("diagonal", rect(120, 300, 100, 100)),
      container("same-column", rect(0, 620, 100, 100)),
    ],
    collisionRect: rect(0, 0, 100, 600),
    coordinates: { x: 0, y: 0 },
  });
  assert.deepEqual(dashboardKeyboardCoordinates(key("ArrowDown"), args), { x: 0, y: 370 });
});

test("keyboard leaves the widget in place when no card exists in that direction", () => {
  const args = keyboardArgs({
    containers: [
      container("active", rect(0, 0, 100, 100)),
      container("right", rect(120, 0, 100, 100)),
    ],
    collisionRect: rect(0, 0, 100, 100),
    coordinates: { x: 0, y: 0 },
  });
  assert.equal(dashboardKeyboardCoordinates(key("ArrowLeft"), args), undefined);
  assert.equal(dashboardKeyboardCoordinates(key("ArrowUp"), args), undefined);
  assert.equal(dashboardKeyboardCoordinates(key("Space"), args), undefined);
});
