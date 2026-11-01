import pytest

from fetchlist.pom import Refused, scan_pom


def pom(body, head=""):
    return f"""<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>g</groupId><artifactId>app</artifactId><version>1.0</version>
{head}
{body}
</project>
"""


def scan(text):
    return [(f.ref, f.status) for f in scan_pom(text, "pom.xml")]


def test_exact_range_latest_and_snapshot():
    body = """<dependencies>
  <dependency><groupId>a</groupId><artifactId>exact</artifactId><version>1.2.3</version></dependency>
  <dependency><groupId>a</groupId><artifactId>range</artifactId><version>[1.0,2.0)</version></dependency>
  <dependency><groupId>a</groupId><artifactId>latest</artifactId><version>LATEST</version></dependency>
  <dependency><groupId>a</groupId><artifactId>release</artifactId><version>RELEASE</version></dependency>
  <dependency><groupId>a</groupId><artifactId>snap</artifactId><version>1.0-SNAPSHOT</version></dependency>
</dependencies>"""
    assert scan(pom(body)) == [
        ("a:exact:1.2.3", "pinned"),
        ("a:range:[1.0,2.0)", "unpinned"),
        ("a:latest:LATEST", "unpinned"),
        ("a:release:RELEASE", "unpinned"),
        ("a:snap:1.0-SNAPSHOT", "unpinned"),
    ]


def test_properties_are_followed():
    body = "<dependencies><dependency><groupId>a</groupId><artifactId>x</artifactId><version>${x.version}</version></dependency></dependencies>"
    assert scan(pom(body, "<properties><x.version>2.0</x.version></properties>")) == [("a:x:2.0", "pinned")]
    assert scan(pom(body)) == [("a:x:${x.version}", "unresolved")]


def test_a_plugin_without_a_version_is_unpinned_unless_it_is_managed():
    body = "<build><plugins><plugin><artifactId>maven-jar-plugin</artifactId></plugin></plugins></build>"
    assert scan(pom(body)) == [("org.apache.maven.plugins:maven-jar-plugin", "unpinned")]
    managed = """<build>
  <pluginManagement><plugins><plugin><artifactId>maven-jar-plugin</artifactId><version>3.5.1</version></plugin></plugins></pluginManagement>
  <plugins><plugin><artifactId>maven-jar-plugin</artifactId></plugin></plugins>
</build>"""
    assert ("org.apache.maven.plugins:maven-jar-plugin:3.5.1", "pinned") in scan(pom(managed))
    assert ("org.apache.maven.plugins:maven-jar-plugin", "unpinned") not in scan(pom(managed))


def test_versions_from_dependency_management_and_a_bom():
    body = """<dependencyManagement><dependencies>
  <dependency><groupId>b</groupId><artifactId>bom</artifactId><version>1</version><type>pom</type><scope>import</scope></dependency>
</dependencies></dependencyManagement>
<dependencies><dependency><groupId>b</groupId><artifactId>member</artifactId></dependency></dependencies>"""
    assert ("b:member", "pinned") in scan(pom(body))
    bare = "<dependencies><dependency><groupId>b</groupId><artifactId>member</artifactId></dependency></dependencies>"
    assert scan(pom(bare)) == [("b:member", "unresolved")]


def test_repositories_over_http_are_unpinned_and_https_ones_are_recorded():
    body = """<repositories>
  <repository><id>a</id><url>http://repo.example.com/maven</url></repository>
  <repository><id>b</id><url>https://repo.example.org/maven</url></repository>
</repositories>"""
    found = {f.ref: f for f in scan_pom(pom(body), "pom.xml")}
    assert found["http://repo.example.com/maven"].status == "unpinned"
    assert found["https://repo.example.org/maven"].status == "info"
    assert found["https://repo.example.org/maven"].host == "repo.example.org"


def test_a_pom_with_a_doctype_or_entity_is_refused_not_expanded():
    with pytest.raises(Refused, match="DOCTYPE"):
        scan_pom('<?xml version="1.0"?><!DOCTYPE project [<!ENTITY a "b">]><project/>', "pom.xml")


def test_malformed_xml_is_refused():
    with pytest.raises(Refused, match="well-formed"):
        scan_pom("<project>", "pom.xml")


def test_line_numbers_point_at_the_artifact():
    body = "<dependencies>\n<dependency><groupId>a</groupId><artifactId>x</artifactId><version>1</version></dependency>\n</dependencies>"
    found = scan_pom(pom(body), "pom.xml")
    assert pom(body).splitlines()[found[0].line - 1].count("<artifactId>x</artifactId>") == 1


def test_properties_that_point_at_properties_are_followed():
    body = "<dependencies><dependency><groupId>a</groupId><artifactId>x</artifactId><version>${one}</version></dependency></dependencies>"
    head = "<properties><one>${two}</one><two>${three}</two><three>3.1</three></properties>"
    assert scan(pom(body, head)) == [("a:x:3.1", "pinned")]
