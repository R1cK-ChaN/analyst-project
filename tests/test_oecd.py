"""Unit tests for the OECD Data Explorer / SDMX client."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import requests

from analyst.ingestion.scrapers.oecd import (
    OECDClient,
    OECDDataStructure,
    OECDDataflow,
    OECDDimension,
    OECDObservation,
    OECDRateLimitError,
    OECDResponseFormatError,
    OECDSeries,
    _normalize_date,
)


SAMPLE_JSON = {
    "data": {
        "dataSets": [{
            "series": {
                "0:0": {"observations": {"0": [99.5], "1": [99.8]}},
                "1:0": {"observations": {"0": [100.2]}},
            }
        }],
        "structures": [{
            "dimensions": {
                "series": [
                    {"id": "REF_AREA", "values": [
                        {"id": "USA", "name": "United States"},
                        {"id": "JPN", "name": "Japan"},
                    ]},
                    {"id": "FREQ", "values": [{"id": "M", "name": "Monthly"}]},
                ],
                "observation": [{
                    "id": "TIME_PERIOD",
                    "values": [{"id": "2024-10"}, {"id": "2024-11"}],
                }],
            }
        }],
    }
}

EMPTY_JSON = {
    "data": {
        "dataSets": [{"series": {}}],
        "structures": [{"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": []}]}}],
    }
}

DATAFLOW_XML = """\
<message:Structure
    xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
    xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
    xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow id="DSD_STES@DF_CLI" agencyID="OECD.SDD.STES" version="4.1">
        <common:Annotations>
          <common:Annotation>
            <common:AnnotationTitle>FREQ=M,MEASURE=LI,LASTNPERIODS=10</common:AnnotationTitle>
            <common:AnnotationType>DEFAULT</common:AnnotationType>
          </common:Annotation>
        </common:Annotations>
        <common:Name xml:lang="en">Composite leading indicators</common:Name>
        <common:Description xml:lang="en">CLI dataset</common:Description>
        <structure:Structure>
          <Ref id="DSD_STES" version="4.1" agencyID="OECD.SDD.STES" />
        </structure:Structure>
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>
"""

DATASTRUCTURE_XML = """\
<message:Structure
    xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
    xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
    xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow id="DSD_STES@DF_CLI" agencyID="OECD.SDD.STES" version="4.1">
        <common:Annotations>
          <common:Annotation>
            <common:AnnotationTitle>FREQ=M,MEASURE=LI</common:AnnotationTitle>
            <common:AnnotationType>DEFAULT</common:AnnotationType>
          </common:Annotation>
        </common:Annotations>
        <common:Name xml:lang="en">Composite leading indicators</common:Name>
        <structure:Structure>
          <Ref id="DSD_STES" version="4.1" agencyID="OECD.SDD.STES" />
        </structure:Structure>
      </structure:Dataflow>
    </structure:Dataflows>
    <structure:Codelists>
      <structure:Codelist id="CL_AREA" agencyID="OECD" version="1.1">
        <structure:Code id="USA">
          <common:Name xml:lang="en">United States</common:Name>
        </structure:Code>
        <structure:Code id="JPN">
          <common:Name xml:lang="en">Japan</common:Name>
        </structure:Code>
      </structure:Codelist>
      <structure:Codelist id="CL_FREQ" agencyID="SDMX" version="2.1">
        <structure:Code id="M">
          <common:Name xml:lang="en">Monthly</common:Name>
        </structure:Code>
      </structure:Codelist>
      <structure:Codelist id="CL_MEASURE" agencyID="OECD.SDD.STES" version="1.1">
        <structure:Code id="LI">
          <common:Name xml:lang="en">CLI</common:Name>
        </structure:Code>
      </structure:Codelist>
    </structure:Codelists>
    <structure:Concepts>
      <structure:ConceptScheme id="CS_STES" agencyID="OECD.SDD.STES" version="4.0">
        <structure:Concept id="REF_AREA">
          <common:Name xml:lang="en">Reference area</common:Name>
        </structure:Concept>
        <structure:Concept id="FREQ">
          <common:Name xml:lang="en">Frequency</common:Name>
        </structure:Concept>
        <structure:Concept id="MEASURE">
          <common:Name xml:lang="en">Measure</common:Name>
        </structure:Concept>
        <structure:Concept id="TIME_PERIOD">
          <common:Name xml:lang="en">Time period</common:Name>
        </structure:Concept>
      </structure:ConceptScheme>
    </structure:Concepts>
    <structure:DataStructures>
      <structure:DataStructure id="DSD_STES" agencyID="OECD.SDD.STES" version="4.1">
        <common:Name xml:lang="en">Short-term statistics</common:Name>
        <structure:DataStructureComponents>
          <structure:DimensionList id="DimensionDescriptor">
            <structure:Dimension id="REF_AREA" position="1">
              <structure:LocalRepresentation>
                <structure:Enumeration>
                  <Ref id="CL_AREA" agencyID="OECD" version="1.1" />
                </structure:Enumeration>
              </structure:LocalRepresentation>
            </structure:Dimension>
            <structure:Dimension id="FREQ" position="2">
              <structure:LocalRepresentation>
                <structure:Enumeration>
                  <Ref id="CL_FREQ" agencyID="SDMX" version="2.1" />
                </structure:Enumeration>
              </structure:LocalRepresentation>
            </structure:Dimension>
            <structure:Dimension id="MEASURE" position="3">
              <structure:LocalRepresentation>
                <structure:Enumeration>
                  <Ref id="CL_MEASURE" agencyID="OECD.SDD.STES" version="1.1" />
                </structure:Enumeration>
              </structure:LocalRepresentation>
            </structure:Dimension>
            <structure:TimeDimension id="TIME_PERIOD" position="4" />
          </structure:DimensionList>
        </structure:DataStructureComponents>
      </structure:DataStructure>
    </structure:DataStructures>
  </message:Structures>
</message:Structure>
"""


def _mock_response(*, status: int = 200, text: str = "", json_data=None, content_type: str = "application/json"):
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.headers = {"Content-Type": content_type}
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_data)
    return response


class TestNormalizeDate(unittest.TestCase):
    def test_monthly(self):
        self.assertEqual(_normalize_date("2025-12"), "2025-12-01")

    def test_quarterly(self):
        self.assertEqual(_normalize_date("2025-Q4"), "2025-10-01")

    def test_semiannual(self):
        self.assertEqual(_normalize_date("2025-S2"), "2025-07-01")

    def test_weekly(self):
        self.assertEqual(_normalize_date("2025-W02"), "2025-01-06")

    def test_annual(self):
        self.assertEqual(_normalize_date("2024"), "2024-01-01")


class TestParseJson(unittest.TestCase):
    def test_parses_json_response(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON,
            series_id="OECD_CLI_US",
            dataflow="DSD_STES@DF_CLI",
            dataset="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            limit=100,
        )
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], OECDObservation)
        self.assertEqual(result[0].dataflow, "DSD_STES@DF_CLI")
        self.assertEqual(result[0].dataset, "DSD_STES@DF_CLI")
        self.assertEqual(result[0].agency_id, "OECD.SDD.STES")
        self.assertTrue(all(obs.series_id == "OECD_CLI_US" for obs in result))
        self.assertEqual(result[0].date, "2024-11-01")
        self.assertEqual(result[0].dimensions["TIME_PERIOD"], "2024-11")

    def test_generates_series_ids_for_multi_series_payload(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON,
            series_id=None,
            dataflow="DSD_STES@DF_CLI",
            dataset="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            limit=100,
        )
        self.assertEqual(len(result), 3)
        self.assertEqual({obs.series_key for obs in result}, {"USA.M", "JPN.M"})
        self.assertEqual({obs.raw_series_key for obs in result}, {"0:0", "1:0"})
        self.assertEqual({obs.series_id for obs in result}, {
            "OECD.SDD.STES:DSD_STES@DF_CLI:USA.M",
            "OECD.SDD.STES:DSD_STES@DF_CLI:JPN.M",
        })
        usa_obs = [obs for obs in result if obs.dimensions["REF_AREA"] == "USA"]
        self.assertEqual(len(usa_obs), 2)

    def test_multi_series_payload_is_not_globally_truncated(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON,
            series_id=None,
            dataflow="DSD_STES@DF_CLI",
            dataset="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            limit=1,
        )
        self.assertEqual(len(result), 3)

    def test_empty_dataset(self):
        result = OECDClient._parse_json(
            EMPTY_JSON,
            series_id="OECD_CLI_US",
            dataflow="DSD_STES@DF_CLI",
            dataset="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            limit=100,
        )
        self.assertEqual(result, [])

    def test_limits_results(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON,
            series_id="OECD_CLI_US",
            dataflow="DSD_STES@DF_CLI",
            dataset="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            limit=2,
        )
        self.assertEqual(len(result), 2)


class TestStructureParsing(unittest.TestCase):
    def test_parses_dataflow_xml(self):
        root = ET.fromstring(DATAFLOW_XML)
        dataflows = OECDClient._parse_dataflows_xml(root)
        self.assertEqual(len(dataflows), 1)
        dataflow = dataflows[0]
        self.assertEqual(dataflow.id, "DSD_STES@DF_CLI")
        self.assertEqual(dataflow.name, "Composite leading indicators")
        self.assertEqual(dataflow.structure_id, "DSD_STES")
        self.assertEqual(dataflow.defaults["FREQ"], "M")
        self.assertEqual(dataflow.defaults["LASTNPERIODS"], "10")

    def test_parses_datastructure_xml(self):
        dataflow = OECDDataflow(
            id="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            version="4.1",
            name="Composite leading indicators",
            structure_id="DSD_STES",
            structure_agency_id="OECD.SDD.STES",
            structure_version="4.1",
            defaults={"FREQ": "M", "MEASURE": "LI"},
        )
        root = ET.fromstring(DATASTRUCTURE_XML)
        structure = OECDClient._parse_datastructure_xml(root, dataflow=dataflow)
        self.assertEqual(structure.id, "DSD_STES")
        self.assertEqual(structure.name, "Short-term statistics")
        self.assertEqual([dim.id for dim in structure.dimensions], [
            "REF_AREA", "FREQ", "MEASURE", "TIME_PERIOD",
        ])
        self.assertEqual(structure.dimensions[0].codes[0].id, "USA")
        self.assertTrue(structure.dimensions[-1].is_time)
        self.assertEqual(structure.defaults["MEASURE"], "LI")


class TestKeyBuilding(unittest.TestCase):
    def test_build_key_uses_defaults(self):
        client = OECDClient()
        client.get_structure = MagicMock(return_value=OECDDataStructure(
            id="DSD_STES",
            agency_id="OECD.SDD.STES",
            version="4.1",
            dimensions=(
                OECDDimension(id="REF_AREA", position=1),
                OECDDimension(id="FREQ", position=2),
                OECDDimension(id="MEASURE", position=3),
                OECDDimension(id="TIME_PERIOD", position=4, is_time=True),
            ),
            defaults={"FREQ": "M", "MEASURE": "LI"},
        ))
        key = client.build_key(
            "DSD_STES@DF_CLI",
            {"REF_AREA": "USA"},
            use_defaults=True,
        )
        self.assertEqual(key, "USA.M.LI")

    def test_build_key_rejects_unknown_dimensions(self):
        client = OECDClient()
        client.get_structure = MagicMock(return_value=OECDDataStructure(
            id="DSD_STES",
            agency_id="OECD.SDD.STES",
            version="4.1",
            dimensions=(OECDDimension(id="REF_AREA", position=1),),
        ))
        with self.assertRaises(ValueError):
            client.build_key("DSD_STES@DF_CLI", {"MEASURE": "LI"})

    def test_series_to_filters_uses_structure_order(self):
        client = OECDClient()
        client.get_structure = MagicMock(return_value=OECDDataStructure(
            id="DSD_STES",
            agency_id="OECD.SDD.STES",
            version="4.1",
            dimensions=(
                OECDDimension(id="REF_AREA", position=1),
                OECDDimension(id="FREQ", position=2),
                OECDDimension(id="MEASURE", position=3),
                OECDDimension(id="TIME_PERIOD", position=4, is_time=True),
            ),
        ))
        filters = client.series_to_filters(
            "DSD_STES@DF_CLI",
            OECDSeries(key="USA.M.LI", dimensions={
                "MEASURE": "LI",
                "REF_AREA": "USA",
                "FREQ": "M",
            }),
        )
        self.assertEqual(filters, {
            "REF_AREA": "USA",
            "FREQ": "M",
            "MEASURE": "LI",
        })


class TestClientRequests(unittest.TestCase):
    def test_list_dataflows_retries_structure_request_as_xml(self):
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(
                text='{"resources":[],"references":{}}',
                json_data={"resources": [], "references": {}},
                content_type="application/json",
            ),
            _mock_response(
                text=DATAFLOW_XML,
                json_data=None,
                content_type="application/xml",
            ),
        ]
        client = OECDClient(session=session)
        dataflows = client.list_dataflows(agency_id="OECD.SDD.STES")
        self.assertEqual(len(dataflows), 1)
        self.assertEqual(dataflows[0].id, "DSD_STES@DF_CLI")

    def test_get_data_constructs_url_and_params(self):
        session = MagicMock()
        session.get.return_value = _mock_response(
            text="{}",
            json_data=EMPTY_JSON,
        )
        client = OECDClient(session=session)

        client.get_data(
            "DSD_STES@DF_CLI",
            "4.1",
            "USA.M.LI",
            series_id="OECD_CLI_US",
            start_period="2024-01",
            end_period="2024-12",
            limit=5,
        )

        args, kwargs = session.get.call_args
        self.assertEqual(
            args[0],
            "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,4.1/USA.M.LI",
        )
        self.assertEqual(kwargs["params"]["format"], "jsondata")
        self.assertEqual(kwargs["params"]["startPeriod"], "2024-01")
        self.assertEqual(kwargs["params"]["endPeriod"], "2024-12")
        self.assertEqual(kwargs["params"]["lastNObservations"], "5")

    def test_wildcard_query_falls_back_to_v2_route_after_404(self):
        session = MagicMock()
        not_found = _mock_response(
            status=404,
            text="NoResultsFound",
            json_data=None,
            content_type="text/plain",
        )
        not_found.raise_for_status.side_effect = requests.HTTPError("404")
        session.get.side_effect = [
            not_found,
            _mock_response(
                text="{}",
                json_data=EMPTY_JSON,
                content_type="application/json",
            ),
        ]
        client = OECDClient(session=session)

        result = client.fetch_data(
            "DSD_STES@DF_CS",
            version="4.0",
            key="USA.M.CCICP.*.*.*.*.*.*",
            series_id="OECD_CONSUMER_CONF_US",
        )

        self.assertEqual(result, [])
        first_url = session.get.call_args_list[0].args[0]
        second_url = session.get.call_args_list[1].args[0]
        self.assertIn("/public/rest/data/", first_url)
        self.assertIn("/public/rest/v2/data/dataflow/", second_url)

    def test_enumerate_series_parses_returned_series_catalog(self):
        session = MagicMock()
        session.get.return_value = _mock_response(
            text="{}",
            json_data=SAMPLE_JSON,
        )
        client = OECDClient(session=session)
        series = client.enumerate_series(
            "DSD_STES@DF_CLI",
            key="USA+JPN.M",
            observation_limit=1,
        )
        self.assertEqual(len(series), 2)
        self.assertEqual(series[0].key, "USA.M")
        self.assertEqual(series[0].raw_key, "0:0")
        self.assertEqual(series[0].dimensions["REF_AREA"], "USA")

    def test_summarize_structure_returns_compact_metadata(self):
        client = OECDClient()
        client.get_dataflow = MagicMock(return_value=OECDDataflow(
            id="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            version="4.1",
            name="Composite leading indicators",
            description="CLI dataset",
        ))
        client.get_structure = MagicMock(return_value=OECDDataStructure(
            id="DSD_STES",
            agency_id="OECD.SDD.STES",
            version="4.1",
            name="Short-term statistics",
            dimensions=(
                OECDDimension(id="REF_AREA", position=1, codes=()),
                OECDDimension(id="FREQ", position=2, codes=(object(),)),
                OECDDimension(id="TIME_PERIOD", position=3, is_time=True),
            ),
            defaults={"FREQ": "M"},
        ))
        summary = client.summarize_structure("DSD_STES@DF_CLI")
        self.assertEqual(summary.dataflow_id, "DSD_STES@DF_CLI")
        self.assertEqual(summary.time_dimension_id, "TIME_PERIOD")
        self.assertEqual(summary.series_dimensions, ("REF_AREA", "FREQ"))
        self.assertEqual(summary.defaults["FREQ"], "M")

    def test_no_results_text_returns_empty_list(self):
        session = MagicMock()
        session.get.return_value = _mock_response(
            text="NoResultsFound",
            json_data=None,
            content_type="text/plain",
        )
        client = OECDClient(session=session)
        result = client.fetch_data(
            "DSD_STES@DF_CLI",
            version="4.1",
            key="USA.M.LI",
            series_id="OECD_CLI_US",
        )
        self.assertEqual(result, [])

    def test_rate_limit_raises_specific_error(self):
        session = MagicMock()
        response = _mock_response(
            status=429,
            text="Too many requests",
            json_data=None,
            content_type="text/plain",
        )
        response.headers["Retry-After"] = "60"
        session.get.return_value = response
        client = OECDClient(session=session)

        with self.assertRaises(OECDRateLimitError):
            client.fetch_data(
                "DSD_STES@DF_CLI",
                version="4.1",
                key="USA.M.LI",
                series_id="OECD_CLI_US",
            )

    def test_unexpected_plain_text_raises_format_error(self):
        session = MagicMock()
        session.get.return_value = _mock_response(
            text="Something went wrong",
            json_data=None,
            content_type="text/plain",
        )
        client = OECDClient(session=session)

        with self.assertRaises(OECDResponseFormatError):
            client.fetch_data(
                "DSD_STES@DF_CLI",
                version="4.1",
                key="USA.M.LI",
                series_id="OECD_CLI_US",
            )


if __name__ == "__main__":
    unittest.main()
