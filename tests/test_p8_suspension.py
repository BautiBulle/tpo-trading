"""Pruebas unitarias P8 sin conexiones a motores reales."""
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.problemas import p8_suspension as p8


class TestP8Suspension(unittest.TestCase):
    def setUp(self):
        self.instrumento = uuid4()
        self.operador = uuid4()
        self.suspension = uuid4()
        self.orden = uuid4()
        self.portafolio = uuid4()
        self.usuario = uuid4()
        self.db = MagicMock()
        self.db.sagas.find_one.return_value = None
        self.db.instrumentos.find_one_and_update.return_value = {"estado": "ACTIVO"}
        self.db.instrumentos.update_one.return_value.matched_count = 1
        self.db.ordenes.find.return_value = []
        self.db.ordenes.count_documents.return_value = 0
        self.patches = [
            patch.object(p8, "get_mongo_db", return_value=self.db),
            patch.object(p8, "obtener_instrumento", return_value={"_id": str(self.instrumento), "simbolo": "ABC", "estado": "ACTIVO"}),
            patch.object(p8, "registrar_auditoria"),
            patch.object(p8, "cancelar_orden"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_suspension_sin_ordenes(self):
        resultado = p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", self.suspension)
        self.assertEqual(resultado["estado"], "SUSPENDIDO")
        self.assertEqual(resultado["canceladas"], [])
        p8.registrar_auditoria.assert_called_once()
        self.db.instrumentos.update_one.assert_called_once()

    def test_cancela_orden_pendiente(self):
        self.db.ordenes.find.return_value = [{"_id": str(self.orden)}]
        resultado = p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", self.suspension)
        self.assertEqual(resultado["canceladas"], [str(self.orden)])
        p8.cancelar_orden.assert_called_once()
        self.assertEqual(p8.cancelar_orden.call_args.args[0], self.orden)

    def test_falla_conserva_suspension_y_permite_reintento(self):
        with self.assertRaisesRegex(RuntimeError, "Falla simulada"):
            p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", self.suspension, "DESPUES_BLOQUEO")
        self.db.instrumentos.update_one.assert_not_called()
        self.db.sagas.update_one.assert_called_with(
            {"_id": str(self.suspension)}, {"$set": {"estado": "REQUIERE_REVISION"}}
        )
        resultado = p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", self.suspension)
        self.assertEqual(resultado["estado"], "SUSPENDIDO")

    def test_no_confirma_si_hay_ordenes_abiertas(self):
        self.db.ordenes.count_documents.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "Quedan 1 órdenes"):
            p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", self.suspension)
        p8.registrar_auditoria.assert_not_called()
        self.db.instrumentos.update_one.assert_not_called()

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            p8.suspender_instrumento("no-uuid", self.operador, "Riesgo")
        with self.assertRaises(ValueError):
            p8.suspender_instrumento(self.instrumento, self.operador, "  ")
        with self.assertRaises(ValueError):
            p8.suspender_instrumento(self.instrumento, self.operador, "Riesgo", forzar_falla="OTRA")
        with self.assertRaises(ValueError):
            p8.trazar_orden(self.orden, margen_segundos=0)

    def test_trazabilidad_ejecucion_confirmada(self):
        ejecucion = uuid4()
        fecha = datetime.now(timezone.utc)
        orden = {"_id": str(self.orden), "idInstrumento": str(self.instrumento),
                 "idPortafolio": str(self.portafolio), "ejecucionesConfirmadas": [str(ejecucion)]}
        self.db.sagas.find.return_value = [{"_id": str(ejecucion), "estado": "COMPLETADA",
            "datos": {"idEjecucion": str(ejecucion), "fechaHora": fecha}}]
        with patch.object(p8, "obtener_orden", return_value=orden), \
             patch.object(p8, "obtener_portafolio", return_value={"idUsuario": str(self.usuario)}), \
             patch.object(p8, "consultar_operaciones_instrumento", return_value=[{"id_operacion": ejecucion}]), \
             patch.object(p8, "consultar_precios", return_value=[]), \
             patch.object(p8, "get_precio", return_value=None), \
             patch.object(p8, "obtener_posicion", return_value=None), \
             patch.object(p8, "consultar_saldo", return_value=None):
            resultado = p8.trazar_orden(self.orden)
            self.assertTrue(resultado["trazabilidadCompleta"])
            self.assertEqual(len(resultado["ejecuciones"]), 1)

    def test_trazabilidad_detecta_historial_faltante(self):
        ejecucion = uuid4()
        orden = {"idInstrumento": str(self.instrumento), "idPortafolio": str(self.portafolio),
                 "ejecucionesConfirmadas": [str(ejecucion)]}
        self.db.sagas.find.return_value = []
        with patch.object(p8, "obtener_orden", return_value=orden), \
             patch.object(p8, "obtener_portafolio", return_value={"idUsuario": str(self.usuario)}), \
             patch.object(p8, "get_precio", return_value=None), \
             patch.object(p8, "obtener_posicion", return_value=None), \
             patch.object(p8, "consultar_saldo", return_value=None):
            resultado = p8.trazar_orden(self.orden)
            self.assertFalse(resultado["trazabilidadCompleta"])


if __name__ == "__main__":
    unittest.main()
