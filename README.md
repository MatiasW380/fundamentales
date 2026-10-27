# Momentum CEDEARs

Dashboard que dice qué CEDEARs comprar según la regla de momentum 12-1 (la única que pasó las pruebas del laboratorio fundamental).

- `scripts/actualizar.py` baja precios de Yahoo, elige la cartera y simula la historia; si hay `SEC_USER_AGENT`, baja los balances de las empresas de la SEC.
- `.github/workflows/actualizar.yml` lo corre de lunes a viernes después del cierre de Nueva York y commitea `data/`. Vercel publica solo.
- Cuando cambia la cartera (último día hábil de feb, may, ago y nov) se abre un issue en el repo y GitHub avisa por mail.
- `config.json`: lista de CEDEARs, cantidad de acciones, meses de revisión y costo por operación.
- `lab/`: celdas de Colab del laboratorio original (referencia, ya no hace falta correrlas).
