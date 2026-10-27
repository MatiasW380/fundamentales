# Operación automática con PPI (pendiente de implementar)

Reglas acordadas para el día de cada revisión (último día hábil de feb, may, ago y nov; la primera, 30/11/2026):

1. **Vender** las acciones que salen de la cartera momentum (cantidad completa que tiene el bot).
2. **Comprar** con **todo el efectivo** disponible en la cuenta ese día (incluye dividendos cobrados y lo obtenido por las ventas),
   buscando que cada una de las 5 acciones quede cerca del **20%**.
3. **Solo se tocan las 5 acciones de la cartera momentum.** Cualquier otro instrumento de la cuenta (comprado a mano) se ignora:
   no se cuenta en el cálculo y nunca se vende.

## A definir antes de programarlo
- Moneda: ¿se opera el CEDEAR en pesos o en dólares (MEP)? ¿Qué efectivo cuenta, pesos, dólares o ambos?
- Si el titular compra a mano alguna de las mismas 5 acciones, ¿esas unidades también son del bot?
- Las que siguen en cartera y quedaron por encima del 20%: ¿se recortan, o solo se compra lo que falta en las demás?
- Si una acción no tiene CEDEAR o no tiene precio ese día: se saltea y se reparte entre las demás.
