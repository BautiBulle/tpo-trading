"""Pruebas unitarias del Problema 7, sin motores externos."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.problemas.p7_riesgo import detectar_concentracion_riesgo, detectar_operaciones_espejo


class TestP7Riesgo(unittest.TestCase):
    @patch('app.problemas.p7_riesgo.get_precio')
    @patch('app.problemas.p7_riesgo.listar_posiciones_portafolio')
    @patch('app.problemas.p7_riesgo.get_mongo_db')
    def test_concentracion_sectorial(self, mongo, posiciones, precio):
        usuario, portafolio, a, b = [uuid4() for _ in range(4)]
        db = MagicMock()
        db.instrumentos.find.return_value = [
            {'_id': str(a), 'simbolo': 'AAA', 'sector': 'TECNOLOGIA'},
            {'_id': str(b), 'simbolo': 'BBB', 'sector': 'ENERGIA'},
        ]
        db.portafolios.find.return_value = [{'_id': str(portafolio), 'idUsuario': str(usuario)}]
        mongo.return_value = db
        posiciones.return_value = [
            {'idInstrumento': str(a), 'cantidad': Decimal('3')},
            {'idInstrumento': str(b), 'cantidad': Decimal('1')},
        ]
        precio.return_value = {'ultimo': Decimal('100')}
        resultado = detectar_concentracion_riesgo(Decimal('70'))
        self.assertEqual(len(resultado['alertas']), 1)
        self.assertEqual(resultado['alertas'][0]['sector'], 'TECNOLOGIA')
        self.assertEqual(resultado['alertas'][0]['porcentaje'], Decimal('75'))

    @patch('app.problemas.p7_riesgo.get_mongo_db')
    def test_sin_tenencias_no_alerta(self, mongo):
        db = MagicMock()
        db.instrumentos.find.return_value = []
        db.portafolios.find.return_value = []
        mongo.return_value = db
        self.assertEqual(detectar_concentracion_riesgo()['alertas'], [])

    def test_umbral_invalido(self):
        with self.assertRaises(ValueError):
            detectar_concentracion_riesgo(101)

    @patch('app.problemas.p7_riesgo.consultar_operaciones_instrumento')
    @patch('app.problemas.p7_riesgo.get_mongo_db')
    def test_operaciones_en_espejo(self, mongo, consultar):
        db = MagicMock()
        db.instrumentos.find.return_value = [{'_id': str(uuid4()), 'simbolo': 'AAA'}]
        mongo.return_value = db
        ahora = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
        u1, u2 = uuid4(), uuid4()
        consultar.return_value = [
            {'id_operacion': uuid4(), 'id_usuario': u1, 'tipo': 'COMPRA', 'fecha_hora': ahora, 'cantidad': Decimal('1'), 'precio': Decimal('10')},
            {'id_operacion': uuid4(), 'id_usuario': u2, 'tipo': 'COMPRA', 'fecha_hora': ahora + timedelta(seconds=3), 'cantidad': Decimal('2'), 'precio': Decimal('10')},
            {'id_operacion': uuid4(), 'id_usuario': uuid4(), 'tipo': 'VENTA', 'fecha_hora': ahora + timedelta(seconds=4), 'cantidad': Decimal('1'), 'precio': Decimal('10')},
        ]
        resultado = detectar_operaciones_espejo(ahora - timedelta(seconds=1), ahora + timedelta(seconds=10))
        self.assertEqual(len(resultado['alertas']), 1)
        self.assertEqual(resultado['alertas'][0]['tipo'], 'COMPRA')
        self.assertEqual(len(resultado['alertas'][0]['usuarios']), 2)
        consultar.assert_called_once_with('AAA', ahora - timedelta(seconds=1), ahora + timedelta(seconds=10))

    @patch('app.problemas.p7_riesgo.consultar_operaciones_instrumento')
    @patch('app.problemas.p7_riesgo.get_mongo_db')
    def test_mismo_usuario_no_es_espejo(self, mongo, consultar):
        db = MagicMock()
        db.instrumentos.find.return_value = [{'simbolo': 'AAA'}]
        mongo.return_value = db
        ahora = datetime(2026, 10, 20, tzinfo=timezone.utc)
        usuario = uuid4()
        consultar.return_value = [
            {'id_operacion': uuid4(), 'id_usuario': usuario, 'tipo': 'COMPRA', 'fecha_hora': ahora, 'cantidad': Decimal('1'), 'precio': Decimal('10')},
            {'id_operacion': uuid4(), 'id_usuario': usuario, 'tipo': 'COMPRA', 'fecha_hora': ahora + timedelta(seconds=1), 'cantidad': Decimal('1'), 'precio': Decimal('10')},
        ]
        self.assertEqual(detectar_operaciones_espejo(ahora, ahora + timedelta(seconds=10))['alertas'], [])

    def test_fechas_sin_zona_horaria(self):
        with self.assertRaises(ValueError):
            detectar_operaciones_espejo(datetime(2026, 10, 20), datetime(2026, 10, 21))


if __name__ == '__main__':
    unittest.main()
