SELECT apartamento_id, año_aplicable, mes_aplicable,
  COALESCE(SUM(
    CASE
      WHEN tipo_movimiento = 'DEBITO' THEN monto
      WHEN tipo_movimiento = 'CREDITO' THEN -monto
      ELSE 0
    END
  ), 0) AS saldo
FROM registro_financiero_apartamento AS rfa where apartamento_id =3 and año_aplicable = 2025
GROUP BY apartamento_id,año_aplicable, mes_aplicable
ORDER BY año_aplicable, mes_aplicable;





SELECT apartamento_id,
  COALESCE(SUM(
    CASE
      WHEN tipo_movimiento = 'DEBITO' THEN monto
      WHEN tipo_movimiento = 'CREDITO' THEN -monto
      ELSE 0
    END
  ), 0) AS saldo
FROM registro_financiero_apartamento AS rfa
GROUP BY apartamento_id
HAVING COALESCE(SUM(
    CASE
      WHEN tipo_movimiento = 'DEBITO' THEN monto
      WHEN tipo_movimiento = 'CREDITO' THEN -monto
      ELSE 0
    END
  ), 0) > 0
ORDER BY apartamento_id;



-- Saldo por apartamento:

SELECT apartamento_id,
  COALESCE(SUM(
    CASE
      WHEN tipo_movimiento = 'DEBITO' THEN monto
      WHEN tipo_movimiento = 'CREDITO' THEN -monto
      ELSE 0
    END
  ), 0) AS saldo
FROM registro_financiero_apartamento AS rfa
WHERE apartamento_id = 10
GROUP BY apartamento_id



"""
    Calcula el saldo para un apartamento específico sumando los créditos
    y restando los débitos.
    """
    # 1. Define la expresión CASE para asignar signo al monto
    monto_con_signo = case(
        (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
        (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
        else_=0
    )

    # 2. Construye la consulta completa
    statement = select(
        rfa.apartamento_id,
        func.coalesce(
            func.sum(monto_con_signo),
            0
        ).label("saldo")
    ).group_by(
        rfa.apartamento_id
    ).having(
        func.coalesce(func.sum(monto_con_signo), 0) > 0  # Solo saldos positivos
    ).order_by(
        rfa.apartamento_id
    )

Me parece que generador pagos es demasiado verbosa y podría simplificarse en lo que se refiere a los intereses.

Para implementar la funcionalidad de generación automática de pagos y cuotas de administración, debemos seguir un proceso que asegure que los intereses, la aplicación de saldos a favor y que las cuotas ordinarias se calculen y registren correctamente en la base de datos.

Fundamental, dar inicio al proceso del calculo de intereses y luego continuar con las demás responsabilidades del generador de pagos.

Para ello, podríamos seguir la siguiente logica:
1. Calcular y grabar con el concepto 3 en la tabla registro_financiero_apartamento los intereses de los apartamentos que tengan saldo DEBITO.

Desarrollo del numeral 1

a) Buscamos los apartamentos con saldo DEBITO:

"""
    Calcula el saldo para un apartamento específico sumando los créditos
    y restando los débitos.
    """
    # 1. Define la expresión CASE para asignar signo al monto
    monto_con_signo = case(
        (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
        (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
        else_=0
    )

    # 2. Construye la consulta completa
    statement = select(
        rfa.apartamento_id,
        func.coalesce(
            func.sum(monto_con_signo),
            0
        ).label("saldo")
    ).group_by(
        rfa.apartamento_id
    ).having(
        func.coalesce(func.sum(monto_con_signo), 0) > 0  # Solo saldos positivos
    ).order_by(
        rfa.apartamento_id
    )
"""

b) Para el calculo de los intereses, se puede utilizar la siguiente lógica:

Buscamos en el modelo TasaInteres el interés vigente para el mes anterior al actual (tal vez usando una consulta donde se  busque el registro del mayor((año+mes)*100-1), y luego calculamos los intereses de cada apartamento con saldo DEBITO.

Grabamos los intereses en registro_financiero_apartamento teniendo en cuenta que año_aplicable y mes_aplicable será correspondiente con el año y mes  del registro encontrado en el modelo TasaInteres con la condicion where max((año+mes)*100) es decir un mes despúes del usado para el calculo de interes
